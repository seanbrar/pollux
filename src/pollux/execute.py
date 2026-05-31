"""Phase 3: Plan execution with caching, uploads, and rate limiting."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any

from pollux._singleflight import singleflight_cached
from pollux.capabilities import validate_capabilities
from pollux.continuation import (
    build_conversation_state,
    history_text_from_parts,
    history_to_messages,
    load_continuation,
)
from pollux.errors import APIError, ConfigurationError, InternalError, PolluxError
from pollux.providers.base import FileDeletingProvider, ValidatingProvider
from pollux.providers.models import (
    Message,
    ProviderFileAsset,
    ProviderRequest,
    ProviderResponse,
)
from pollux.retry import (
    RetryPolicy,
    retry_async,
    should_retry_generate,
    should_retry_side_effect,
)

if TYPE_CHECKING:
    from pollux.plan import Plan
    from pollux.providers.base import Provider

logger = logging.getLogger(__name__)


async def _validate_provider_request(
    provider: Provider,
    request: ProviderRequest,
) -> None:
    """Run provider-owned validation before uploads or other side effects."""
    if isinstance(provider, ValidatingProvider):
        await provider.validate_request(request)


def _with_call_idx(err: APIError, call_idx: int | None) -> APIError:
    """Return an APIError instance attributed to *call_idx*.

    Important for shared single-flight failures (ex: file uploads): the same
    exception instance may be observed by multiple concurrent calls, so avoid
    mutating it in-place.
    """
    if call_idx is None or err.call_idx is not None:
        return err

    message = err.args[0] if err.args else str(err)
    cls: type[APIError] = type(err)
    return cls(
        message,
        hint=err.hint,
        retryable=err.retryable,
        status_code=err.status_code,
        retry_after_s=err.retry_after_s,
        provider=err.provider,
        phase=err.phase,
        call_idx=call_idx,
    )


@dataclass
class ExecutionTrace:
    """Trace of execution with responses and metrics."""

    responses: list[ProviderResponse] = field(default_factory=list)
    cache_name: str | None = None
    duration_s: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    conversation_state: dict[str, Any] | None = None


async def execute_plan(plan: Plan, provider: Provider) -> ExecutionTrace:
    """Execute the plan with the given provider.

    Handles:
    - Caching (with single-flight protection)
    - File uploads (when needed)
    - Concurrent call execution
    """
    start_time = time.perf_counter()
    config = plan.request.config
    options = plan.request.options
    model = config.model
    prompts = plan.request.prompts
    caps = provider.capabilities

    wants_conversation = (
        options.history is not None or options.continue_from is not None
    )

    # Belt-and-suspenders: Options.__post_init__ already rejects "deferred",
    # but guard here in case validation is ever bypassed.
    if options.delivery_mode == "deferred":
        raise ConfigurationError(
            "delivery_mode='deferred' is a legacy compatibility shim and is not supported",
            hint="Use pollux.defer() or pollux.defer_many() for deferred delivery.",
        )
    has_file_parts = any(
        isinstance(p, dict)
        and isinstance(p.get("file_path"), str)
        and isinstance(p.get("mime_type"), str)
        for p in plan.shared_parts
    )
    validate_capabilities(
        options,
        caps,
        n_prompts=len(prompts),
        has_file_parts=has_file_parts,
        cache_requested=plan.cache_name is not None,
    )

    schema = options.response_schema_json()

    continuation = load_continuation(options)
    history = continuation.history
    conversation_history = continuation.conversation_history
    previous_response_id = continuation.previous_response_id
    provider_state = continuation.provider_state

    upload_cache: dict[tuple[str, str], ProviderFileAsset] = {}
    upload_inflight: dict[tuple[str, str], asyncio.Future[ProviderFileAsset]] = {}
    upload_lock = asyncio.Lock()
    retry_policy = config.retry
    responses: list[ProviderResponse] = []
    implicit_caching = (
        options.implicit_caching
        if options.implicit_caching is not None
        else caps.implicit_caching and len(prompts) == 1
    )
    total_usage: dict[str, int] = {}
    conversation_state: dict[str, Any] | None = None
    conversation_user_contents: list[str | None] = [None] * len(prompts)

    try:
        cache_name = plan.cache_name

        # Execute calls with concurrency control
        concurrency = config.request_concurrency
        sem = asyncio.Semaphore(concurrency)
        logger.debug(
            "Executing %d call(s) concurrency=%d cache=%s",
            len(prompts),
            concurrency,
            cache_name or "disabled",
        )

        async def _execute_call(call_idx: int) -> ProviderResponse:
            async with sem:
                try:
                    # Build parts: shared context + prompt
                    shared_parts = (
                        [] if cache_name is not None else list(plan.shared_parts)
                    )
                    prompt_part = prompts[call_idx]
                    raw_parts = (
                        [*shared_parts, prompt_part]
                        if prompt_part is not None
                        else [*shared_parts]
                    )
                    conversation_user_contents[call_idx] = history_text_from_parts(
                        raw_parts
                    )
                    history_msgs: list[Message] | None = None
                    request_provider_state = (
                        dict(provider_state)
                        if isinstance(provider_state, dict)
                        else None
                    )
                    if history is not None:
                        history_msgs, history_item_states = history_to_messages(history)
                        if history_item_states is not None:
                            if request_provider_state is None:
                                request_provider_state = {}
                            request_provider_state["history"] = history_item_states
                    req = ProviderRequest(
                        model=model,
                        parts=raw_parts,
                        system_instruction=options.system_instruction,
                        cache_name=cache_name,
                        response_schema=schema,
                        temperature=options.temperature,
                        top_p=options.top_p,
                        tools=options.tools,
                        tool_choice=options.tool_choice,
                        reasoning_effort=options.reasoning_effort,
                        reasoning_budget_tokens=options.reasoning_budget_tokens,
                        history=history_msgs,
                        previous_response_id=previous_response_id,
                        provider_state=request_provider_state,
                        max_tokens=options.max_tokens,
                        implicit_caching=implicit_caching,
                    )
                    await _validate_provider_request(provider, req)
                    parts = await _substitute_upload_parts(
                        raw_parts,
                        provider=provider,
                        call_idx=call_idx,
                        upload_cache=upload_cache,
                        upload_inflight=upload_inflight,
                        upload_lock=upload_lock,
                        retry_policy=retry_policy,
                    )
                    req = replace(req, parts=parts)

                    if retry_policy.max_attempts <= 1:
                        resp = await provider.generate(req)
                    else:
                        resp = await retry_async(
                            lambda: provider.generate(req),
                            policy=retry_policy,
                            should_retry=should_retry_generate,
                        )

                    return resp

                except asyncio.CancelledError:
                    raise
                except APIError as e:
                    if e.call_idx is None:
                        e.call_idx = call_idx
                    raise
                except PolluxError:
                    raise
                except Exception as e:
                    from pollux.providers._errors import wrap_provider_error

                    provider_name = (
                        type(provider).__name__.lower().replace("provider", "")
                    )
                    wrapped_err = wrap_provider_error(
                        e,
                        provider=provider_name,
                        phase="generate",
                        allow_network_errors=True,
                        message=f"{provider_name.capitalize()} generate failed",
                    )
                    if getattr(wrapped_err, "call_idx", None) is None:
                        wrapped_err.call_idx = call_idx
                    raise wrapped_err from e

        # Execute all calls. We intentionally collect *all* task outcomes before
        # raising so failures don't leave background tasks with unobserved
        # exceptions.
        tasks = [asyncio.create_task(_execute_call(i)) for i in range(len(prompts))]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for item in results:
            if isinstance(item, asyncio.CancelledError):
                raise item
            if isinstance(item, BaseException):
                # Deterministic: prefer lowest call index, not "first to fail".
                raise item

        for item in results:
            if not isinstance(item, ProviderResponse):
                raise InternalError(
                    f"Provider returned invalid response type: {type(item).__name__}",
                    hint="Providers must return a ProviderResponse.",
                )
            responses.append(item)

        # Aggregate usage
        for resp in responses:
            for k, v in resp.usage.items():
                if isinstance(v, int):
                    total_usage[k] = total_usage.get(k, 0) + v

        # Build conversation state when either (a) the caller opted in via
        # history/continue_from, or (b) the response contains tool calls that
        # the caller may need to continue via continue_tool/continue_from.
        conversation_state = build_conversation_state(
            responses,
            first_prompt=prompts[0] if prompts else None,
            first_user_content=conversation_user_contents[0]
            if conversation_user_contents
            else None,
            conversation_history=conversation_history,
            previous_response_id=previous_response_id,
            wants_conversation=wants_conversation,
        )
    finally:
        # Clean up uploaded files (best-effort; server-side TTL is the backstop).
        await _cleanup_uploads(upload_cache, provider)

    duration_s = time.perf_counter() - start_time

    return ExecutionTrace(
        responses=responses,
        cache_name=cache_name,
        duration_s=duration_s,
        usage=total_usage,
        conversation_state=conversation_state,
    )


async def _substitute_upload_parts(
    parts: list[Any],
    *,
    provider: Provider,
    call_idx: int | None,
    upload_cache: dict[tuple[str, str], ProviderFileAsset],
    upload_inflight: dict[tuple[str, str], asyncio.Future[ProviderFileAsset]],
    upload_lock: asyncio.Lock,
    retry_policy: RetryPolicy,
) -> list[Any]:
    """Replace local file placeholders with provider file assets."""
    resolved: list[Any] = []

    for part in parts:
        if (
            isinstance(part, dict)
            and isinstance(part.get("file_path"), str)
            and isinstance(part.get("mime_type"), str)
        ):
            file_path = part["file_path"]
            mime_type = part["mime_type"]
            provider_hints = part.get("provider_hints")
            cache_key = (file_path, mime_type)

            async def _work(
                fp: str = file_path, mt: str = mime_type
            ) -> ProviderFileAsset:
                try:
                    if retry_policy.max_attempts <= 1:
                        return await provider.upload_file(Path(fp), mt)

                    return await retry_async(
                        lambda: provider.upload_file(Path(fp), mt),
                        policy=retry_policy,
                        should_retry=should_retry_side_effect,
                    )
                except PolluxError:
                    raise
                except Exception as e:
                    raise InternalError(
                        f"Upload failed: {type(e).__name__}: {e}",
                        hint="This is a Pollux internal error. Please report it.",
                    ) from e

            try:
                asset = await singleflight_cached(
                    cache_key,
                    lock=upload_lock,
                    inflight=upload_inflight,
                    cache_get=upload_cache.get,
                    cache_set=upload_cache.__setitem__,
                    work=_work,
                )
            except APIError as e:
                raise _with_call_idx(e, call_idx) from e

            # The provider adapter reconstructs the SDK payload from the uploaded asset.
            if provider_hints is not None:
                resolved.append(
                    {
                        "uri": asset.file_id,
                        "mime_type": mime_type,
                        "provider_hints": provider_hints,
                    }
                )
            else:
                resolved.append(asset)
            continue

        resolved.append(part)

    return resolved


_OPENAI_FILE_PREFIX = "openai://file/"


async def _cleanup_uploads(
    upload_cache: dict[tuple[str, str], ProviderFileAsset],
    provider: Provider,
) -> None:
    """Delete provider-managed uploaded files (best-effort).

    Only applies to providers that expose a ``delete_file`` method (currently
    OpenAI). Failures are logged but never raised—the server-side TTL is the
    backstop.
    """
    if not isinstance(provider, FileDeletingProvider):
        return

    file_ids: list[str] = []
    for asset in upload_cache.values():
        if asset.provider == "openai" and not asset.is_inline_fallback:
            file_ids.append(asset.file_id)

    for file_id in file_ids:
        try:
            await provider.delete_file(file_id)
            logger.debug("Deleted uploaded file: %s", file_id)
        except Exception as exc:
            logger.debug("Failed to delete uploaded file %s: %s", file_id, exc)
