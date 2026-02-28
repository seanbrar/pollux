"""Phase 3: Plan execution with caching, uploads, and rate limiting."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any

from pollux._singleflight import singleflight_cached
from pollux.cache import CacheRegistry, get_or_create_cache
from pollux.errors import APIError, ConfigurationError, InternalError, PolluxError
from pollux.providers.models import Message, ProviderRequest, ToolCall
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

    responses: list[dict[str, Any]] = field(default_factory=list)
    cache_name: str | None = None
    duration_s: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    conversation_state: dict[str, Any] | None = None


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
    model = config.model
    prompts = plan.request.prompts
    caps = provider.capabilities

    wants_conversation = (
        options.history is not None or options.continue_from is not None
    )

    # TODO: implement deferred delivery via provider batch APIs.
    if options.delivery_mode == "deferred":
        provider_name = type(provider).__name__
        raise ConfigurationError(
            f"delivery_mode='deferred' is not implemented yet for provider {provider_name}",
            hint="Use delivery_mode='realtime' for now.",
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
    if wants_conversation and not caps.conversation:
        raise ConfigurationError(
            "Provider does not support conversation continuity",
            hint="Remove history/continue_from or choose a provider with conversation support.",
        )
    if wants_conversation and len(prompts) != 1:
        raise ConfigurationError(
            "Conversation continuity currently supports exactly one prompt per call",
            hint="Use run() or run_many() with a single prompt when passing history/continue_from.",
        )

    if (not provider.supports_uploads) and any(
        isinstance(p, dict)
        and isinstance(p.get("file_path"), str)
        and isinstance(p.get("mime_type"), str)
        for p in plan.shared_parts
    ):
        raise ConfigurationError(
            "Provider does not support file uploads",
            hint="Choose a provider with uploads support, or remove file sources.",
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

    upload_cache: dict[tuple[str, str], str] = {}
    upload_inflight: dict[tuple[str, str], asyncio.Future[str]] = {}
    upload_lock = asyncio.Lock()
    retry_policy = config.retry
    cache_name: str | None = None
    responses: list[dict[str, Any]] = []
    total_usage: dict[str, int] = {}
    conversation_state: dict[str, Any] | None = None

    try:
        # Handle caching
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
                        system_instruction=options.system_instruction,
                        ttl_seconds=config.ttl_seconds,
                        retry_policy=retry_policy,
                    )
                except asyncio.CancelledError:
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
        logger.debug(
            "Executing %d call(s) concurrency=%d cache=%s",
            len(prompts),
            concurrency,
            cache_name or "disabled",
        )

        async def _execute_call(call_idx: int) -> dict[str, Any]:
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
                    parts = await _substitute_upload_parts(
                        raw_parts,
                        provider=provider,
                        call_idx=call_idx,
                        upload_cache=upload_cache,
                        upload_inflight=upload_inflight,
                        upload_lock=upload_lock,
                        retry_policy=retry_policy,
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
                        parts=parts,
                        system_instruction=options.system_instruction,
                        cache_name=cache_name,
                        response_schema=schema,
                        temperature=options.temperature,
                        top_p=options.top_p,
                        tools=options.tools,
                        tool_choice=options.tool_choice,
                        reasoning_effort=options.reasoning_effort,
                        history=history_msgs,
                        previous_response_id=previous_response_id,
                        provider_state=request_provider_state,
                    )

                    if retry_policy.max_attempts <= 1:
                        resp = await provider.generate(req)
                    else:
                        resp = await retry_async(
                            lambda: provider.generate(req),
                            policy=retry_policy,
                            should_retry=should_retry_generate,
                        )

                    out: dict[str, Any] = {"text": resp.text, "usage": resp.usage}
                    if resp.reasoning is not None:
                        out["reasoning"] = resp.reasoning
                    if resp.structured is not None:
                        out["structured"] = resp.structured
                    if resp.tool_calls is not None:
                        out["tool_calls"] = [
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in resp.tool_calls
                        ]
                    if resp.response_id is not None:
                        out["response_id"] = resp.response_id
                    if resp.finish_reason is not None:
                        out["finish_reason"] = resp.finish_reason
                    if resp.provider_state is not None:
                        out["provider_state"] = resp.provider_state
                    return out

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
            if not isinstance(item, dict):
                raise InternalError(
                    f"Provider returned invalid response type: {type(item).__name__}",
                    hint="Providers must return dict payloads with at least a 'text' field.",
                )
            responses.append(item)

        # Aggregate usage
        for resp in responses:
            usage = resp.get("usage", {})
            for k, v in usage.items():
                if isinstance(v, int):
                    total_usage[k] = total_usage.get(k, 0) + v

        # Build conversation state when either (a) the caller opted in via
        # history/continue_from, or (b) the response contains tool calls that
        # the caller may need to continue via continue_tool/continue_from.
        has_tool_calls = bool(responses and responses[0].get("tool_calls"))
        if (wants_conversation or has_tool_calls) and responses:
            prompt = (
                prompts[0]
                if isinstance(prompts[0], str)
                else str(prompts[0])
                if prompts[0] is not None
                else None
            )
            answer = responses[0].get("text")
            reply = answer if isinstance(answer, str) else ""
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": reply}
            tool_calls = responses[0].get("tool_calls")
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            provider_msg_state = responses[0].get("provider_state")
            if isinstance(provider_msg_state, dict):
                assistant_msg["provider_state"] = provider_msg_state

            updated_history: list[dict[str, Any]] = [*conversation_history]
            if prompt is not None:
                updated_history.append({"role": "user", "content": prompt})
            updated_history.append(assistant_msg)
            conversation_state = {"history": updated_history}
            if isinstance(provider_msg_state, dict):
                conversation_state["provider_state"] = provider_msg_state
            response_id = responses[0].get("response_id")
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
            file_path = part["file_path"]
            mime_type = part["mime_type"]
            cache_key = (file_path, mime_type)

            async def _work(fp: str = file_path, mt: str = mime_type) -> str:
                try:
                    if retry_policy.max_attempts <= 1:
                        return await provider.upload_file(Path(fp), mt)

                    return await retry_async(
                        lambda: provider.upload_file(Path(fp), mt),
                        policy=retry_policy,
                        should_retry=should_retry_side_effect,
                    )
                except APIError:
                    raise
                except Exception as e:
                    raise InternalError(
                        f"Upload failed: {type(e).__name__}: {e}",
                        hint="This is a Pollux internal error. Please report it.",
                    ) from e

            try:
                uri = await singleflight_cached(
                    cache_key,
                    lock=upload_lock,
                    inflight=upload_inflight,
                    cache_get=upload_cache.get,
                    cache_set=upload_cache.__setitem__,
                    work=_work,
                )
            except APIError as e:
                raise _with_call_idx(e, call_idx) from e

            resolved.append({"uri": uri, "mime_type": mime_type})
            continue

        resolved.append(part)

    return resolved


_OPENAI_FILE_PREFIX = "openai://file/"


async def _cleanup_uploads(
    upload_cache: dict[tuple[str, str], str],
    provider: Provider,
) -> None:
    """Delete provider-managed uploaded files (best-effort).

    Only applies to providers that expose a ``delete_file`` method (currently
    OpenAI). Failures are logged but never raised—the server-side TTL is the
    backstop.
    """
    delete_fn = getattr(provider, "delete_file", None)
    if delete_fn is None or not callable(delete_fn):
        return

    file_ids: list[str] = []
    for uri in upload_cache.values():
        if uri.startswith(_OPENAI_FILE_PREFIX):
            file_ids.append(uri[len(_OPENAI_FILE_PREFIX) :])

    for file_id in file_ids:
        try:
            await delete_fn(file_id)
            logger.debug("Deleted uploaded file: %s", file_id)
        except Exception as exc:
            logger.debug("Failed to delete uploaded file %s: %s", file_id, exc)
