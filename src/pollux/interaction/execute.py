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
from pollux.errors import APIError, ConfigurationError, InternalError, PolluxError
from pollux.interaction._uploads import cleanup_uploads, substitute_upload_parts
from pollux.interaction.capabilities import resolve_capabilities
from pollux.interaction.collection import OutputCollection
from pollux.interaction.continuation import build_continuation
from pollux.interaction.environment import CachePolicy, EnvironmentSnapshot
from pollux.interaction.event import Event
from pollux.interaction.extract import provider_response_to_output
from pollux.interaction.output import Usage
from pollux.interaction.tools import ToolCall
from pollux.interaction.validate import validate_interaction
from pollux.parts import build_shared_parts, history_text_from_parts
from pollux.providers import _compile
from pollux.providers.base import (
    FileUploadingProvider,
    StreamingProvider,
    ValidatingProvider,
)
from pollux.providers.models import ProviderResponse, is_file_part
from pollux.providers.models import ToolCall as ProviderToolCall
from pollux.retry import retry_async, should_retry_generate

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from typing import Any

    from pollux.config import Config
    from pollux.interaction.environment import Environment
    from pollux.interaction.input import Input
    from pollux.interaction.output import Output
    from pollux.interaction.requirements import OutputRequirements
    from pollux.providers.base import Provider
    from pollux.providers.models import ProviderFileAsset


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
        continuation = build_continuation(
            inputs[idx],
            response,
            user_content=user_contents[idx],
            provider=config.provider,
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


class _ToolCallAssembler:
    """Reassemble streamed tool-call fragments into ordered, complete calls.

    Fragments arrive keyed by ``index``: the opening fragment for a slot usually
    carries ``id``/``name`` and later fragments append argument text. Slots are
    emitted in first-seen order so the assembled calls match arrival order.
    """

    def __init__(self) -> None:
        self._order: list[int] = []
        self._slots: dict[int, dict[str, Any]] = {}

    def add(self, delta: Any) -> None:
        """Merge one :class:`ToolCallDelta` fragment into its slot."""
        slot = self._slots.get(delta.index)
        if slot is None:
            slot = {"id": None, "name": None, "arguments": []}
            self._slots[delta.index] = slot
            self._order.append(delta.index)
        if delta.id:
            slot["id"] = delta.id
        if delta.name:
            slot["name"] = delta.name
        if delta.arguments:
            slot["arguments"].append(delta.arguments)

    def assembled(self) -> list[tuple[ToolCall, ProviderToolCall]]:
        """Return ``(public ToolCall, transport ToolCall)`` pairs, in order."""
        pairs: list[tuple[ToolCall, ProviderToolCall]] = []
        for index in self._order:
            slot = self._slots[index]
            call_id = slot["id"] or f"call_{index}"
            name = slot["name"] or ""
            arguments = "".join(slot["arguments"])
            public = ToolCall.from_text(
                id=call_id, name=name, arguments_text=arguments, index=index
            )
            transport = ProviderToolCall(id=call_id, name=name, arguments=arguments)
            pairs.append((public, transport))
        return pairs


async def stream_interaction(
    environment: Environment,
    input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
    requirements: OutputRequirements,
    config: Config,
    provider: Provider,
) -> AsyncIterator[Event]:
    """Stream one interaction as :class:`Event` objects, ending in ``done``.

    Same orchestration as :func:`execute_interaction` (capability validation,
    uploads, cache resolution, continuation, ``Output`` assembly), observed as a
    timeline: text/reasoning/tool-call deltas as the provider emits them, then a
    terminal ``done`` whose ``output`` matches the non-streaming result. A
    mid-stream provider failure raises from the iterator instead of emitting
    ``done``. Streamed turns are single-input and are not retried mid-stream.
    """
    start_time = time.perf_counter()
    snapshot = EnvironmentSnapshot.from_environment(
        environment, provider=config.provider
    )
    caps = resolve_capabilities(provider.capabilities, config.capabilities)
    persistent_requested = isinstance(snapshot.cache, CachePolicy)
    validate_interaction(
        requirements, [input], snapshot, caps, cache_requested=persistent_requested
    )

    if not isinstance(provider, StreamingProvider):
        raise ConfigurationError(
            "Provider does not support streaming",
            hint="Use a streaming-capable provider, or call interact() for a "
            "single blocking Output.",
        )

    if isinstance(provider, ValidatingProvider):
        await provider.validate_request(snapshot, input, requirements, config)

    upload_cache: dict[tuple[str, str], ProviderFileAsset] = {}
    snapshot, cache_mode = await _prepare_snapshot(
        snapshot, 1, config, provider, caps, upload_cache
    )
    user_content = history_text_from_parts(_compile.request_parts(snapshot, input))

    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls = _ToolCallAssembler()
    usage: dict[str, int] = {}
    provider_state: dict[str, Any] = {}
    finish_reason: str | None = None
    response_id: str | None = None

    try:
        yield Event(type="start")
        async for chunk in provider.stream_generate(
            snapshot, input, requirements, config
        ):
            if chunk.text:
                text_parts.append(chunk.text)
                yield Event(type="text_delta", text=chunk.text)
            if chunk.reasoning:
                reasoning_parts.append(chunk.reasoning)
                yield Event(type="reasoning_delta", text=chunk.reasoning)
            for delta in chunk.tool_calls:
                tool_calls.add(delta)
                yield Event(type="tool_call_delta", delta=delta)
            if chunk.usage:
                # Usage may stream across several chunks (e.g. Anthropic reports
                # input at message_start and output at message_delta), so merge
                # rather than replace and surface the cumulative snapshot.
                usage.update(chunk.usage)
                yield Event(type="usage", usage=Usage.from_dict(usage))
            if chunk.provider_state:
                provider_state.update(chunk.provider_state)
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
            if chunk.response_id:
                response_id = chunk.response_id

        assembled = tool_calls.assembled()
        for public_call, _transport in assembled:
            yield Event(type="tool_call", tool_call=public_call)
        if finish_reason is not None:
            yield Event(type="finish", finish_reason=finish_reason)

        response = ProviderResponse(
            text="".join(text_parts),
            usage=usage,
            reasoning="".join(reasoning_parts) or None,
            tool_calls=[transport for _public, transport in assembled] or None,
            response_id=response_id,
            finish_reason=finish_reason,
            provider_state=provider_state or None,
        )
        duration_s = time.perf_counter() - start_time
        cached = usage.get("cached_tokens", 0)
        cache_used = cache_mode == "persistent"
        cache_hit = cache_used or (
            cache_mode == "implicit" and isinstance(cached, int) and cached > 0
        )
        continuation = build_continuation(
            input, response, user_content=user_content, provider=config.provider
        )
        output = provider_response_to_output(
            response,
            requirements=requirements,
            duration_s=duration_s,
            cache_used=cache_used,
            cache_mode=cache_mode,
            cache_hit=cache_hit,
            continuation=continuation,
        )
        yield Event(type="done", output=output)
    finally:
        await cleanup_uploads(upload_cache, provider)
