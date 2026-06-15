"""Continuation conversion between the v1 ``ConversationState`` and v2 ``Continuation``.

The v2 execution path persists conversation state as a typed
:class:`~pollux.interaction.continuation.Continuation`, but the underlying
serialization and replay machinery still speaks the v1 ``ConversationState``
history-dict shape. These helpers convert between the two; they are internal.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pollux.continuation import ConversationState
from pollux.interaction.continuation import Continuation, Message
from pollux.interaction.tools import ToolCall

if TYPE_CHECKING:
    from collections.abc import Mapping


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
