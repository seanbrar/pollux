"""Phase 3: Plan execution with caching, uploads, and rate limiting."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import os
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any

from pollux.cache import CacheRegistry, get_or_create_cache
from pollux.errors import APIError, ConfigurationError, InternalError, PolluxError
from pollux.retry import (
    RetryPolicy,
    retry_async,
    should_retry_generate,
    should_retry_side_effect,
)

if TYPE_CHECKING:
    from pollux.options import Options
    from pollux.plan import Plan
    from pollux.providers.base import Provider


def _consume_future_exception(fut: asyncio.Future[Any]) -> None:
    """Avoid 'Future exception was never retrieved' for coordination futures."""
    try:
        _ = fut.exception()
    except asyncio.CancelledError:
        return


@dataclass
class ExecutionTrace:
    """Trace of execution with responses and metrics."""

    responses: list[dict[str, Any]] = field(default_factory=list)
    cache_name: str | None = None
    duration_s: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)


async def execute_plan(
    plan: Plan, provider: Provider, registry: CacheRegistry
) -> ExecutionTrace:
    """Execute the plan with the given provider.

    Handles:
    - Caching (with single-flight protection)
    - File uploads (when needed)
    - Concurrent call execution
    """
    start_time = time.perf_counter()
    config = plan.request.config
    options = plan.request.options
    _validate_feature_lifecycle(options)
    _validate_provider_capabilities(options, provider)
    _validate_upload_requirements(plan, provider)
    schema = options.response_schema_json()
    history, previous_response_id = _resolve_conversation_inputs(options)

    upload_cache: dict[tuple[str, str], str] = {}
    upload_inflight: dict[tuple[str, str], asyncio.Future[str]] = {}
    upload_lock = asyncio.Lock()
    retry_policy = config.retry

    # Handle caching
    cache_name = None
    if plan.use_cache:
        # Resolve uploads for shared parts first, as cache creation requires URIs
        shared_parts = list(plan.shared_parts)
        if shared_parts:
            shared_parts = await _substitute_upload_parts(
                shared_parts,
                provider=provider,
                call_idx=None,
                upload_cache=upload_cache,
                upload_inflight=upload_inflight,
                upload_lock=upload_lock,
                retry_policy=retry_policy,
            )

        if plan.cache_key:
            try:
                cache_name = await get_or_create_cache(
                    provider,
                    registry,
                    key=plan.cache_key,
                    model=config.model,
                    parts=shared_parts,  # Use resolved parts with URIs
                    system_instruction=None,
                    ttl_seconds=config.ttl_seconds,
                    retry_policy=retry_policy,
                )
            except asyncio.CancelledError:
                raise
            except APIError:
                raise
            except PolluxError:
                raise
            except Exception as e:
                raise InternalError(
                    f"Cache creation failed: {type(e).__name__}: {e}",
                    hint="This is a Pollux internal error. Please report it.",
                ) from e

    # Execute calls with concurrency control
    concurrency = config.request_concurrency
    sem = asyncio.Semaphore(concurrency)
    responses: list[dict[str, Any]] = []

    async def _execute_call(call_idx: int) -> dict[str, Any]:
        call = plan.calls[call_idx]
        async with sem:
            try:
                # Build parts: shared context + prompt
                shared_parts = [] if cache_name is not None else list(call.parts)
                raw_parts = [*shared_parts, call.prompt]
                parts = await _substitute_upload_parts(
                    raw_parts,
                    provider=provider,
                    call_idx=call_idx,
                    upload_cache=upload_cache,
                    upload_inflight=upload_inflight,
                    upload_lock=upload_lock,
                    retry_policy=retry_policy,
                )

                if retry_policy.max_attempts <= 1:
                    return await provider.generate(
                        model=call.model,
                        parts=parts,
                        system_instruction=call.system_instruction,
                        cache_name=cache_name,
                        response_schema=schema,
                        reasoning_effort=options.reasoning_effort,
                        history=history,
                        delivery_mode=options.delivery_mode,
                        previous_response_id=previous_response_id,
                    )

                return await retry_async(
                    lambda: provider.generate(
                        model=call.model,
                        parts=parts,
                        system_instruction=call.system_instruction,
                        cache_name=cache_name,
                        response_schema=schema,
                        reasoning_effort=options.reasoning_effort,
                        history=history,
                        delivery_mode=options.delivery_mode,
                        previous_response_id=previous_response_id,
                    ),
                    policy=retry_policy,
                    should_retry=should_retry_generate,
                )
            except asyncio.CancelledError:
                raise
            except APIError as e:
                if e.call_idx is None:
                    e.call_idx = call_idx
                raise
            except PolluxError:
                raise
            except Exception as e:
                raise InternalError(
                    f"Call {call_idx} failed: {type(e).__name__}: {e}",
                    hint="This is a Pollux internal error. Please report it.",
                ) from e

    # Execute all calls
    results = await asyncio.gather(*[_execute_call(i) for i in range(len(plan.calls))])
    responses = list(results)

    # Aggregate usage
    total_usage: dict[str, int] = {}
    for resp in responses:
        usage = resp.get("usage", {})
        for k, v in usage.items():
            if isinstance(v, int):
                total_usage[k] = total_usage.get(k, 0) + v

    duration_s = time.perf_counter() - start_time

    return ExecutionTrace(
        responses=responses,
        cache_name=cache_name,
        duration_s=duration_s,
        usage=total_usage,
    )


async def _substitute_upload_parts(
    parts: list[Any],
    *,
    provider: Provider,
    call_idx: int | None,
    upload_cache: dict[tuple[str, str], str],
    upload_inflight: dict[tuple[str, str], asyncio.Future[str]],
    upload_lock: asyncio.Lock,
    retry_policy: RetryPolicy,
) -> list[Any]:
    """Replace local file placeholders with provider URIs."""
    resolved: list[Any] = []

    for part in parts:
        if (
            isinstance(part, dict)
            and isinstance(part.get("file_path"), str)
            and isinstance(part.get("mime_type"), str)
        ):
            if not provider.supports_uploads:
                raise ConfigurationError(
                    "Provider does not support file uploads",
                    hint="Choose a provider with uploads support, or remove file sources.",
                )

            file_path = part["file_path"]
            mime_type = part["mime_type"]
            cache_key = (file_path, mime_type)

            async with upload_lock:
                uri = upload_cache.get(cache_key)
                if uri is not None:
                    fut = None
                    creator = False
                elif cache_key in upload_inflight:
                    fut = upload_inflight[cache_key]
                    creator = False
                else:
                    fut = asyncio.get_running_loop().create_future()
                    fut.add_done_callback(_consume_future_exception)
                    upload_inflight[cache_key] = fut
                    creator = True

            if uri is None:
                if not creator:
                    if fut is None:
                        raise InternalError(
                            "Upload coordination failure",
                            hint="This is a Pollux internal error. Please report it.",
                        )
                    try:
                        uri = await fut
                    except asyncio.CancelledError:
                        raise
                    except APIError:
                        raise
                else:
                    if fut is None:
                        raise InternalError(
                            "Upload coordination failure",
                            hint="This is a Pollux internal error. Please report it.",
                        )
                    try:
                        uploaded_uri: str
                        if retry_policy.max_attempts <= 1:
                            uploaded_uri = await provider.upload_file(
                                Path(file_path), mime_type
                            )
                        else:

                            async def _upload(
                                fp: str = file_path, mt: str = mime_type
                            ) -> str:
                                return await provider.upload_file(Path(fp), mt)

                            uploaded_uri = await retry_async(
                                _upload,
                                policy=retry_policy,
                                should_retry=should_retry_side_effect,
                            )
                        async with upload_lock:
                            upload_cache[cache_key] = uploaded_uri
                        uri = uploaded_uri
                    except asyncio.CancelledError:
                        fut.cancel()
                        raise
                    except Exception as e:
                        if isinstance(e, APIError):
                            if e.call_idx is None:
                                e.call_idx = call_idx
                            fut.set_exception(e)
                            raise

                        mapped = InternalError(
                            f"Upload failed: {type(e).__name__}: {e}",
                            hint="This is a Pollux internal error. Please report it.",
                        )
                        fut.set_exception(mapped)
                        raise mapped from e
                    else:
                        fut.set_result(uploaded_uri)
                    finally:
                        async with upload_lock:
                            upload_inflight.pop(cache_key, None)

            if uri is None:
                raise InternalError(
                    "Upload coordination failure",
                    hint="This is a Pollux internal error. Please report it.",
                )

            resolved.append({"uri": uri, "mime_type": mime_type})
            continue

        resolved.append(part)

    return resolved


def _validate_provider_capabilities(options: Options, provider: Provider) -> None:
    """Fail fast when requested options are unsupported by the provider."""
    caps = provider.capabilities

    if options.delivery_mode == "deferred":
        provider_name = type(provider).__name__
        raise ConfigurationError(
            f"delivery_mode='deferred' is not implemented yet for provider {provider_name}",
            hint="Use delivery_mode='realtime' for v1.0.",
        )

    if options.response_schema is not None and not caps.structured_outputs:
        raise ConfigurationError(
            "Provider does not support structured outputs",
            hint="Remove response_schema or choose a provider with schema support.",
        )
    if options.reasoning_effort is not None and not caps.reasoning:
        raise ConfigurationError(
            "Provider does not support reasoning controls",
            hint="Remove reasoning_effort or choose a provider with reasoning support.",
        )
    if (options.history is not None or options.continue_from is not None) and (
        not caps.conversation
    ):
        raise ConfigurationError(
            "Provider does not support conversation continuity",
            hint="Remove history/continue_from or choose a provider with conversation support.",
        )


def _validate_upload_requirements(plan: Plan, provider: Provider) -> None:
    """Fail fast when the plan requires file uploads but provider can't upload."""
    if provider.supports_uploads:
        return

    def has_file_part(parts: tuple[Any, ...]) -> bool:
        for p in parts:
            if (
                isinstance(p, dict)
                and isinstance(p.get("file_path"), str)
                and isinstance(p.get("mime_type"), str)
            ):
                return True
        return False

    if has_file_part(plan.shared_parts) or any(
        has_file_part(c.parts) for c in plan.calls
    ):
        raise ConfigurationError(
            "Provider does not support file uploads",
            hint="Choose a provider with uploads support, or remove file sources.",
        )


def _validate_feature_lifecycle(options: Options) -> None:
    """Fail fast for API shapes that are accepted but not yet released."""
    wants_conversation = (
        options.history is not None or options.continue_from is not None
    )
    if wants_conversation and not _is_enabled("POLLUX_EXPERIMENTAL_CONVERSATION"):
        raise ConfigurationError(
            "Conversation options are reserved for a future release",
            hint=(
                "Remove history/continue_from for now, or set "
                "POLLUX_EXPERIMENTAL_CONVERSATION=1 to opt in during development."
            ),
        )


def _is_enabled(env_var: str) -> bool:
    """Return True when an environment flag is set to a truthy value."""
    return os.environ.get(env_var, "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_conversation_inputs(
    options: Options,
) -> tuple[list[dict[str, str]] | None, str | None]:
    """Resolve conversation inputs from explicit history or continue_from."""
    if options.continue_from is None:
        return options.history, None

    state = options.continue_from.get("_conversation_state")
    if not isinstance(state, dict):
        raise ConfigurationError(
            "continue_from is missing _conversation_state",
            hint="Pass a prior Pollux ResultEnvelope produced with conversation support.",
        )

    history = options.history
    if history is None:
        state_history = state.get("history")
        if isinstance(state_history, list):
            history = [
                item
                for item in state_history
                if isinstance(item, dict)
                and isinstance(item.get("role"), str)
                and isinstance(item.get("content"), str)
            ]

    previous_response_id = state.get("response_id")
    if not isinstance(previous_response_id, str):
        previous_response_id = None

    return history, previous_response_id
