"""Phase 3: Plan execution with caching, uploads, and rate limiting."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import json
import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any

from pollux._singleflight import singleflight_cached
from pollux.capabilities import validate_capabilities
from pollux.errors import APIError, ConfigurationError, InternalError, PolluxError
from pollux.providers.base import FileDeletingProvider, ValidatingProvider
from pollux.providers.models import (
    Message,
    ProviderFileAsset,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
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

    history = options.history
    conversation_history: list[dict[str, Any]] = []
    if history is not None:
        conversation_history = [dict(item) for item in history]

    previous_response_id: str | None = None
    provider_state: dict[str, Any] | None = None
    if options.continue_from is not None:
        state = options.continue_from.get("_conversation_state")
        if not isinstance(state, dict):
            raise ConfigurationError(
                "continue_from is missing _conversation_state",
                hint=(
                    "Pass a prior Pollux ResultEnvelope produced with conversation "
                    "support."
                ),
            )

        state_history = state.get("history")
        if history is None and isinstance(state_history, list):
            conversation_history = [
                item
                for item in state_history
                if isinstance(item, dict) and isinstance(item.get("role"), str)
            ]

        if history is None:
            history = conversation_history

        prev = state.get("response_id")
        previous_response_id = prev if isinstance(prev, str) else None
        raw_provider_state = state.get("provider_state")
        if isinstance(raw_provider_state, dict):
            provider_state = dict(raw_provider_state)

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
                    conversation_user_contents[call_idx] = _history_text_from_parts(
                        raw_parts
                    )
                    history_msgs: list[Message] | None = None
                    request_provider_state = (
                        dict(provider_state)
                        if isinstance(provider_state, dict)
                        else None
                    )
                    if history is not None:
                        history_msgs = []
                        history_item_states: list[dict[str, Any] | None] = []
                        has_history_item_states = False
                        for h in history:
                            role = h.get("role", "user")
                            content = h.get("content", "")
                            tc_id = h.get("tool_call_id")
                            msg_provider_state = h.get("provider_state")
                            tcs = None
                            raw_tcs = h.get("tool_calls")
                            if isinstance(raw_tcs, list):
                                tcs = []
                                for tc in raw_tcs:
                                    if isinstance(tc, dict):
                                        raw_args = tc.get("arguments", "")
                                        args_str = (
                                            json.dumps(raw_args)
                                            if isinstance(raw_args, dict)
                                            else str(raw_args)
                                        )
                                        tcs.append(
                                            ToolCall(
                                                id=str(tc.get("id", "")),
                                                name=str(tc.get("name", "")),
                                                arguments=args_str,
                                            )
                                        )
                            if isinstance(msg_provider_state, dict):
                                history_item_states.append(dict(msg_provider_state))
                                has_history_item_states = True
                            else:
                                history_item_states.append(None)
                            history_msgs.append(
                                Message(
                                    role=str(role),
                                    content=content
                                    if isinstance(content, str)
                                    else str(content),
                                    tool_call_id=tc_id
                                    if isinstance(tc_id, str)
                                    else None,
                                    tool_calls=tcs,
                                )
                            )
                        if has_history_item_states:
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
        has_tool_calls = bool(responses and responses[0].tool_calls)
        if (wants_conversation or has_tool_calls) and responses:
            prompt = (
                prompts[0]
                if isinstance(prompts[0], str)
                else str(prompts[0])
                if prompts[0] is not None
                else None
            )
            user_content = conversation_user_contents[0] or prompt
            reply = responses[0].text
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": reply}
            tool_calls = responses[0].tool_calls
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in tool_calls
                ]
            provider_msg_state = responses[0].provider_state
            if isinstance(provider_msg_state, dict):
                assistant_msg["provider_state"] = provider_msg_state

            updated_history: list[dict[str, Any]] = [*conversation_history]
            if user_content is not None:
                updated_history.append({"role": "user", "content": user_content})
            updated_history.append(assistant_msg)
            conversation_state = {"history": updated_history}
            if isinstance(provider_msg_state, dict):
                conversation_state["provider_state"] = provider_msg_state
            response_id = responses[0].response_id
            if isinstance(response_id, str):
                conversation_state["response_id"] = response_id
            elif previous_response_id is not None:
                conversation_state["response_id"] = previous_response_id
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


def _history_text_from_parts(parts: list[Any]) -> str | None:
    """Return a replayable text history message when all parts are text."""
    texts: list[str] = []
    for part in parts:
        if isinstance(part, str):
            texts.append(part)
            continue
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                texts.append(text)
                continue
        return None
    return "\n\n".join(texts) if texts else None


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
