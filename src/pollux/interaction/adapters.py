"""Transitional adapters between v1.x shapes and the v2 interaction model.

These conversions prove the v2 types losslessly represent today's
``ResultEnvelope`` / ``ConversationState`` / ``Options`` while the live pipeline
is untouched. They are scaffolding: Slice 2 makes the provider boundary emit
``Output`` natively, and this module is deleted then. Nothing here is part of the
intended public v2 API.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pollux.continuation import ConversationState
from pollux.interaction.collection import OutputCollection
from pollux.interaction.continuation import Continuation, Message
from pollux.interaction.environment import Environment
from pollux.interaction.input import Input
from pollux.interaction.output import (
    Diagnostics,
    Metrics,
    Output,
    Usage,
    completion_status,
)
from pollux.interaction.requirements import OutputRequirements
from pollux.interaction.tools import ToolCall, ToolDeclaration

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pollux.options import Options
    from pollux.source import Source


def _args_text(raw: Any) -> str:
    """Coerce a v1 tool-call ``arguments`` value to a raw argument string."""
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw)
    except TypeError:
        return str(raw)


def _message_from_history_dict(history: Mapping[str, Any]) -> Message:
    """Convert a v1 history dict into a typed v2 :class:`Message`."""
    raw_tool_calls = history.get("tool_calls")
    tool_calls: tuple[ToolCall, ...] = ()
    if isinstance(raw_tool_calls, list):
        tool_calls = tuple(
            ToolCall.from_text(
                id=str(tc.get("id", "")),
                name=str(tc.get("name", "")),
                arguments_text=_args_text(tc.get("arguments", "")),
            )
            for tc in raw_tool_calls
            if isinstance(tc, dict)
        )
    content = history.get("content", "")
    tool_call_id = history.get("tool_call_id")
    provider_state = history.get("provider_state")
    return Message(
        role=str(history.get("role", "user")),
        content=content if isinstance(content, str) else str(content),
        tool_calls=tool_calls,
        tool_call_id=tool_call_id if isinstance(tool_call_id, str) else None,
        provider_state=provider_state if isinstance(provider_state, dict) else None,
    )


def _history_dict_from_message(message: Message) -> dict[str, Any]:
    """Convert a typed v2 :class:`Message` back into a v1 history dict."""
    payload: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments_text}
            for tc in message.tool_calls
        ]
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if message.provider_state is not None:
        payload["provider_state"] = message.provider_state
    return payload


def continuation_from_state(
    state: ConversationState | Mapping[str, Any],
) -> Continuation:
    """Convert a v1 ``ConversationState`` (or its dict) into a v2 ``Continuation``."""
    resolved = (
        state
        if isinstance(state, ConversationState)
        else ConversationState.from_state_dict(state)
    )
    messages = tuple(_message_from_history_dict(h) for h in resolved.history)
    return Continuation(
        messages=messages,
        response_id=resolved.response_id,
        provider=resolved.provider,
        provider_state=resolved.provider_state,
    )


def state_from_continuation(continuation: Continuation) -> ConversationState:
    """Convert a v2 ``Continuation`` back into a v1 ``ConversationState``."""
    history = [_history_dict_from_message(m) for m in continuation.messages]
    return ConversationState(
        history=history,
        response_id=continuation.response_id,
        provider_state=continuation.provider_state,
        provider=continuation.provider,
    )


def _build_output(
    envelope: Mapping[str, Any],
    index: int,
    *,
    usage: Usage,
) -> Output:
    """Assemble one :class:`Output` from a v1 envelope at *index*."""
    answers = envelope.get("answers") or []
    text = answers[index] if index < len(answers) else ""

    structured_list = envelope.get("structured")
    structured = (
        structured_list[index]
        if isinstance(structured_list, list) and index < len(structured_list)
        else None
    )
    reasoning_list = envelope.get("reasoning")
    reasoning = (
        reasoning_list[index]
        if isinstance(reasoning_list, list) and index < len(reasoning_list)
        else None
    )

    metrics_dict = envelope.get("metrics") or {}
    finish_reasons = metrics_dict.get("finish_reasons") or []
    finish_reason = finish_reasons[index] if index < len(finish_reasons) else None
    metrics = Metrics(
        duration_s=float(metrics_dict.get("duration_s", 0.0)),
        n_calls=1,
        cache_used=bool(metrics_dict.get("cache_used", False)),
        cache_mode=str(metrics_dict.get("cache_mode", "none")),
        cache_hit=bool(metrics_dict.get("cache_hit", False)),
        finish_reason=finish_reason,
        completion_status=completion_status(finish_reason),
    )

    tool_calls_envelope = envelope.get("tool_calls")
    tool_calls: tuple[ToolCall, ...] = ()
    if isinstance(tool_calls_envelope, list) and index < len(tool_calls_envelope):
        tool_calls = tuple(
            ToolCall.from_text(
                id=str(tc.get("id", "")),
                name=str(tc.get("name", "")),
                arguments_text=_args_text(tc.get("arguments", "")),
            )
            for tc in tool_calls_envelope[index]
            if isinstance(tc, dict)
        )

    continuation: Continuation | None = None
    state = envelope.get(ConversationState.ENVELOPE_KEY)
    if isinstance(state, dict):
        continuation = continuation_from_state(state)

    diagnostics_raw = envelope.get("diagnostics")
    diagnostics = Diagnostics(
        raw=dict(diagnostics_raw) if isinstance(diagnostics_raw, dict) else None
    )

    return Output(
        text=text if isinstance(text, str) else str(text),
        structured=structured,
        reasoning=reasoning,
        tool_calls=tool_calls,
        continuation=continuation,
        usage=usage,
        metrics=metrics,
        diagnostics=diagnostics,
    )


def output_from_envelope(envelope: Mapping[str, Any], *, index: int = 0) -> Output:
    """Convert a single-interaction v1 ``ResultEnvelope`` into an ``Output``."""
    return _build_output(
        envelope, index, usage=Usage.from_dict(envelope.get("usage", {}))
    )


def collection_from_envelope(envelope: Mapping[str, Any]) -> OutputCollection:
    """Convert a multi-interaction v1 ``ResultEnvelope`` into an ``OutputCollection``."""
    answers = envelope.get("answers") or []
    diagnostics = envelope.get("diagnostics") or {}
    raw_responses = diagnostics.get("raw_responses") or []
    outputs: list[Output] = []
    for i in range(len(answers)):
        per_call_usage = (
            raw_responses[i].get("usage", {})
            if i < len(raw_responses) and isinstance(raw_responses[i], dict)
            else {}
        )
        outputs.append(
            _build_output(envelope, i, usage=Usage.from_dict(per_call_usage))
        )
    return OutputCollection(
        outputs=tuple(outputs),
        prompt_indexes=tuple(range(len(answers))),
    )


def requirements_from_options(options: Options) -> OutputRequirements:
    """Project the per-generation fields of v1 ``Options`` onto requirements."""
    return OutputRequirements(
        output_schema=options.response_schema,
        temperature=options.temperature,
        top_p=options.top_p,
        max_tokens=options.max_tokens,
        reasoning_effort=options.reasoning_effort,
        reasoning_budget_tokens=options.reasoning_budget_tokens,
        tool_choice=options.tool_choice,
        provider_options=options.provider_options,
    )


def environment_from_options(
    options: Options, sources: Sequence[Source]
) -> Environment:
    """Project the stable-setup fields of v1 ``Options`` onto an environment.

    Concrete v1 ``CacheHandle`` mapping is out of Slice 1 scope (cache-handle
    identity lands with the provider boundary); only the cache-bearing fields
    that decompose cleanly are carried here.
    """
    tools = tuple(ToolDeclaration.from_dict(tool) for tool in (options.tools or ()))
    return Environment(
        instructions=options.system_instruction,
        sources=tuple(sources),
        tools=tools,
    )


def input_from_options(options: Options, prompt: str | None) -> Input:
    """Project a v1 ``Options`` prior-turn state plus *prompt* onto an ``Input``."""
    history: tuple[Message, ...] | None = None
    continuation: Continuation | None = None
    if options.history is not None:
        history = tuple(_message_from_history_dict(h) for h in options.history)
    elif options.continue_from is not None:
        state = ConversationState.from_envelope(options.continue_from)
        if state is not None:
            continuation = continuation_from_state(state)
    return Input(content=prompt, history=history, continuation=continuation)
