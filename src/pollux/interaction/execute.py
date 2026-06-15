"""The v2 execution path: run interactions and assemble ``Output``.

This is the v2 sibling of ``execute.execute_plan``. It owns the core-side
orchestration concerns (capability validation, core-orchestrated file uploads
with single-flight dedup, concurrency, and retry), calls the unchanged provider
transport (``provider.generate``), and assembles immutable ``Output`` /
``OutputCollection`` results. The provider request compilation and response
extraction live in ``interaction/compile.py`` and ``interaction/extract.py``.

The v1 ``run()``/``run_many()`` pipeline is untouched; this path is exercised by
the v2 frontdoors (``interact()``/``run()``) in Slice 3.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import time
from typing import TYPE_CHECKING

from pollux.continuation import build_conversation_state, history_text_from_parts
from pollux.errors import APIError, InternalError, PolluxError
from pollux.execute import (
    _cleanup_uploads,
    _substitute_upload_parts,
    _validate_provider_request,
)
from pollux.interaction.adapters import continuation_from_state, state_from_continuation
from pollux.interaction.collection import OutputCollection
from pollux.interaction.compile import compile_request
from pollux.interaction.continuation import Continuation
from pollux.interaction.environment import EnvironmentSnapshot
from pollux.interaction.extract import provider_response_to_output
from pollux.interaction.validate import validate_interaction
from pollux.providers.models import ProviderResponse
from pollux.retry import retry_async, should_retry_generate

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

    from pollux.config import Config
    from pollux.interaction.environment import Environment
    from pollux.interaction.input import Input
    from pollux.interaction.output import Output
    from pollux.interaction.requirements import OutputRequirements
    from pollux.providers.base import Provider
    from pollux.providers.models import ProviderFileAsset


def _prior_history_dicts(input: Input) -> list[dict[str, Any]]:  # noqa: A002
    """Reconstruct the prior-turn history dicts that precede this interaction."""
    if input.continuation is not None:
        dicts = list(state_from_continuation(input.continuation).history)
    elif input.history is not None:
        dicts = list(
            state_from_continuation(Continuation(messages=tuple(input.history))).history
        )
    else:
        dicts = []
    dicts.extend(
        {"role": "tool", "content": tr.content, "tool_call_id": tr.call_id}
        for tr in input.tool_results
    )
    return dicts


def _build_continuation(
    input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
    response: ProviderResponse,
    user_content: str | None,
    provider: str,
) -> Continuation | None:
    """Assemble the next-turn continuation for one interaction, or ``None``."""
    state = build_conversation_state(
        [response],
        first_prompt=input.content,
        first_user_content=user_content,
        conversation_history=_prior_history_dicts(input),
        previous_response_id=input.continuation.response_id
        if input.continuation is not None
        else None,
        wants_conversation=input.continuation is not None or input.history is not None,
        provider=provider,
    )
    return continuation_from_state(state) if state is not None else None


async def execute_interactions(
    environment: Environment,
    inputs: Sequence[Input],
    requirements: OutputRequirements,
    config: Config,
    provider: Provider,
) -> OutputCollection:
    """Execute one interaction per input over a shared environment.

    Handles capability validation, core-orchestrated uploads (single-flight
    dedup), concurrency, and retry, then assembles per-interaction ``Output``s.
    """
    start_time = time.perf_counter()
    inputs = tuple(inputs)
    snapshot = EnvironmentSnapshot.from_environment(
        environment, provider=config.provider
    )
    caps = provider.capabilities
    validate_interaction(requirements, inputs, snapshot, caps, cache_requested=False)

    implicit_caching = caps.implicit_caching and len(inputs) == 1
    cache_mode = "implicit" if implicit_caching else "none"

    upload_cache: dict[tuple[str, str], ProviderFileAsset] = {}
    upload_inflight: dict[tuple[str, str], asyncio.Future[ProviderFileAsset]] = {}
    upload_lock = asyncio.Lock()
    retry_policy = config.retry
    sem = asyncio.Semaphore(config.request_concurrency)
    user_contents: list[str | None] = [None] * len(inputs)

    async def _execute_call(call_idx: int) -> ProviderResponse:
        async with sem:
            try:
                req = compile_request(
                    snapshot,
                    inputs[call_idx],
                    requirements,
                    config,
                    implicit_caching=implicit_caching,
                )
                user_contents[call_idx] = history_text_from_parts(req.parts)
                await _validate_provider_request(provider, req)
                parts = await _substitute_upload_parts(
                    req.parts,
                    provider=provider,
                    call_idx=call_idx,
                    upload_cache=upload_cache,
                    upload_inflight=upload_inflight,
                    upload_lock=upload_lock,
                    retry_policy=retry_policy,
                )
                req = replace(req, parts=parts)

                if retry_policy.max_attempts <= 1:
                    return await provider.generate(req)
                return await retry_async(
                    lambda: provider.generate(req),
                    policy=retry_policy,
                    should_retry=should_retry_generate,
                )
            except asyncio.CancelledError:
                raise
            except APIError as exc:
                if exc.call_idx is None:
                    exc.call_idx = call_idx
                raise
            except PolluxError:
                raise
            except Exception as exc:
                from pollux.providers._errors import wrap_provider_error

                provider_name = type(provider).__name__.lower().replace("provider", "")
                wrapped = wrap_provider_error(
                    exc,
                    provider=provider_name,
                    phase="generate",
                    allow_network_errors=True,
                    message=f"{provider_name.capitalize()} generate failed",
                )
                if getattr(wrapped, "call_idx", None) is None:
                    wrapped.call_idx = call_idx
                raise wrapped from exc

    responses: list[ProviderResponse] = []
    try:
        tasks = [asyncio.create_task(_execute_call(i)) for i in range(len(inputs))]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Collect all outcomes before raising so a failure never leaves a
        # background task with an unobserved exception. Raise the lowest-index
        # failure for deterministic attribution.
        for item in results:
            if isinstance(item, BaseException):
                raise item
            if not isinstance(item, ProviderResponse):
                raise InternalError(
                    f"Provider returned invalid response type: {type(item).__name__}",
                    hint="Providers must return a ProviderResponse.",
                )
            responses.append(item)
    finally:
        await _cleanup_uploads(upload_cache, provider)

    duration_s = time.perf_counter() - start_time

    outputs: list[Output] = []
    for idx, response in enumerate(responses):
        cached = response.usage.get("cached_tokens", 0)
        cache_hit = cache_mode == "implicit" and isinstance(cached, int) and cached > 0
        continuation = _build_continuation(
            inputs[idx], response, user_contents[idx], config.provider
        )
        outputs.append(
            provider_response_to_output(
                response,
                requirements=requirements,
                duration_s=duration_s,
                cache_used=False,
                cache_mode=cache_mode,
                cache_hit=cache_hit,
                continuation=continuation,
            )
        )

    return OutputCollection(
        outputs=tuple(outputs),
        prompt_indexes=tuple(range(len(inputs))),
    )


async def execute_interaction(
    environment: Environment,
    input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
    requirements: OutputRequirements,
    config: Config,
    provider: Provider,
) -> Output:
    """Execute a single interaction and return its ``Output``."""
    collection = await execute_interactions(
        environment, [input], requirements, config, provider
    )
    return collection.outputs[0]
