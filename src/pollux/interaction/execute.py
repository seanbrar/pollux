"""The v2 execution path: run interactions and assemble ``Output``.

Core owns the orchestration concerns — capability validation, single-flight file
uploads, persistent-cache resolution, concurrency, retry, continuation, and
``Output`` assembly. It freezes the environment's prepared (uploaded) parts and
resolved cache onto an :class:`EnvironmentSnapshot`, then hands the canonical
primitives to ``Provider.generate``, which owns upstream request shaping and
response parsing and returns provider response facets. Core then assembles the
immutable ``Output`` / ``OutputCollection``.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import time
from typing import TYPE_CHECKING

from pollux.cache import create_cache_impl
from pollux.continuation import build_conversation_state, history_text_from_parts
from pollux.errors import APIError, InternalError, PolluxError
from pollux.interaction._uploads import cleanup_uploads, substitute_upload_parts
from pollux.interaction.adapters import continuation_from_state, state_from_continuation
from pollux.interaction.capabilities import resolve_capabilities
from pollux.interaction.collection import OutputCollection
from pollux.interaction.continuation import Continuation
from pollux.interaction.environment import CachePolicy, EnvironmentSnapshot
from pollux.interaction.extract import provider_response_to_output
from pollux.interaction.validate import validate_interaction
from pollux.parts import build_shared_parts
from pollux.providers import _compile
from pollux.providers.base import FileUploadingProvider, ValidatingProvider
from pollux.providers.models import ProviderResponse, is_file_part
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


#: Fallback TTL when a ``CachePolicy`` leaves ``ttl_seconds`` unset.
_DEFAULT_CACHE_TTL_SECONDS = 3600


async def resolve_persistent_cache(
    snapshot: EnvironmentSnapshot,
    config: Config,
    provider: Provider,
) -> str | None:
    """Create or reuse a persistent cache for the environment's stable context.

    Returns the provider cache name, or ``None`` when the environment does not
    request a :class:`CachePolicy`. The cache is keyed by the environment's
    instructions, sources, and tools (its identity), so concurrent or repeated
    calls share one provider-side cache via the module registry's single-flight.
    """
    if not isinstance(snapshot.cache, CachePolicy):
        return None
    tools = [
        {
            "name": decl.name,
            "description": decl.description,
            "parameters": decl.parameters,
        }
        for decl in snapshot.tools
    ] or None
    handle = await create_cache_impl(
        snapshot.sources,
        provider=provider,
        config=config,
        system_instruction=snapshot.instructions,
        tools=tools,
        ttl_seconds=snapshot.cache.ttl_seconds or _DEFAULT_CACHE_TTL_SECONDS,
    )
    return handle.name


async def _prepare_parts(
    snapshot: EnvironmentSnapshot,
    config: Config,
    provider: Provider,
    upload_cache: dict[tuple[str, str], ProviderFileAsset],
) -> tuple[Any, ...]:
    """Build the environment's shared source parts, uploading local files once."""
    raw_parts = build_shared_parts(snapshot.sources, provider=config.provider)
    if any(is_file_part(p) for p in raw_parts):
        if not isinstance(provider, FileUploadingProvider):
            raise InternalError(
                "Provider advertises uploads but does not implement upload_file()",
                hint="Implement FileUploadingProvider for this provider.",
            )
        # Uploads are resolved once upfront and shared across the fan-out; a
        # failure here fails the whole batch, attributed to the first call.
        raw_parts = await substitute_upload_parts(
            raw_parts,
            provider=provider,
            call_idx=0,
            upload_cache=upload_cache,
            upload_inflight={},
            upload_lock=asyncio.Lock(),
            retry_policy=config.retry,
        )
    return tuple(raw_parts)


async def _prepare_snapshot(
    snapshot: EnvironmentSnapshot,
    n_inputs: int,
    config: Config,
    provider: Provider,
    caps: Any,
    upload_cache: dict[tuple[str, str], ProviderFileAsset],
) -> tuple[EnvironmentSnapshot, str]:
    """Freeze resolved cache + uploaded parts onto the snapshot for ``generate``.

    Returns the resolved snapshot and the cache mode reflected on ``Output``
    metrics (``"persistent"`` / ``"implicit"`` / ``"none"``).
    """
    cache_name = await resolve_persistent_cache(snapshot, config, provider)
    if cache_name is not None:
        prepared_parts: tuple[Any, ...] = ()
        implicit_caching = False
        cache_mode = "persistent"
    else:
        prepared_parts = await _prepare_parts(snapshot, config, provider, upload_cache)
        implicit_caching = (
            caps.implicit_caching and n_inputs == 1 and snapshot.cache != "none"
        )
        cache_mode = "implicit" if implicit_caching else "none"
    resolved = replace(
        snapshot,
        prepared_parts=prepared_parts,
        cache_name=cache_name,
        implicit_caching=implicit_caching,
    )
    return resolved, cache_mode


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
    caps = resolve_capabilities(provider.capabilities, config.capabilities)
    persistent_requested = isinstance(snapshot.cache, CachePolicy)
    validate_interaction(
        requirements, inputs, snapshot, caps, cache_requested=persistent_requested
    )

    retry_policy = config.retry
    upload_cache: dict[tuple[str, str], ProviderFileAsset] = {}

    # Provider-owned model-specific validation runs before any upload or cache
    # side effects so a rejected request never leaves remote artifacts behind.
    if isinstance(provider, ValidatingProvider):
        for inp in inputs:
            await provider.validate_request(snapshot, inp, requirements, config)

    snapshot, cache_mode = await _prepare_snapshot(
        snapshot, len(inputs), config, provider, caps, upload_cache
    )

    sem = asyncio.Semaphore(config.request_concurrency)
    user_contents: list[str | None] = [None] * len(inputs)

    async def _execute_call(call_idx: int) -> ProviderResponse:
        async with sem:
            try:
                inp = inputs[call_idx]
                user_contents[call_idx] = history_text_from_parts(
                    _compile.request_parts(snapshot, inp)
                )
                if retry_policy.max_attempts <= 1:
                    return await provider.generate(snapshot, inp, requirements, config)
                return await retry_async(
                    lambda: provider.generate(snapshot, inp, requirements, config),
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
        await cleanup_uploads(upload_cache, provider)

    duration_s = time.perf_counter() - start_time

    cache_used = cache_mode == "persistent"
    outputs: list[Output] = []
    for idx, response in enumerate(responses):
        cached = response.usage.get("cached_tokens", 0)
        if cache_mode == "persistent":
            cache_hit = True
        else:
            cache_hit = (
                cache_mode == "implicit" and isinstance(cached, int) and cached > 0
            )
        continuation = _build_continuation(
            inputs[idx], response, user_contents[idx], config.provider
        )
        outputs.append(
            provider_response_to_output(
                response,
                requirements=requirements,
                duration_s=duration_s,
                cache_used=cache_used,
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
