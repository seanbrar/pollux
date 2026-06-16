"""Stateless helpers for the OpenAI Chat Completions wire format.

Both the self-hosted ``local`` provider and the ``openrouter`` provider speak
OpenAI-compatible Chat Completions over httpx. The request shaping and input
handling differ (local is text-only; OpenRouter handles multimodal parts and
reasoning), but the primitives that read a Chat Completions *response* and shape
its tool vocabulary are identical. This module owns that shared wire vocabulary
so the two adapters parse responses, usage, errors, and tool calls one way.

These helpers are deliberately stateless and provider-neutral. Provider-specific
behavior (reasoning extraction, nested upstream errors, multimodal parts) stays
in the adapters and layers on top of these primitives.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import TYPE_CHECKING, Any

from pollux.interaction.tools import ToolCallDelta
from pollux.providers._utils import to_strict_schema
from pollux.providers.models import ProviderStreamChunk, ToolCall

if TYPE_CHECKING:
    import httpx


def first_choice_message(
    data: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    """Return the first choice and its message, defaulting to ``{}`` when absent."""
    choices = data.get("choices")
    choice: Any = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(choice, Mapping):
        choice = {}
    message: Any = choice.get("message")
    if not isinstance(message, Mapping):
        message = {}
    return choice, message


def extract_message_text(content: Any) -> str:
    """Extract text from a Chat Completions message ``content`` field.

    Accepts both the plain-string form and the structured content-array form,
    concatenating ``{"type": "text", ...}`` items.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    text_parts: list[str] = []
    for item in content:
        if isinstance(item, Mapping) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    return "\n\n".join(text_parts)


def extract_finish_reason(choice: Mapping[str, Any]) -> str | None:
    """Return the choice's ``finish_reason`` when it is a string."""
    finish_reason = choice.get("finish_reason")
    return finish_reason if isinstance(finish_reason, str) else None


def extract_response_id(data: Mapping[str, Any]) -> str | None:
    """Return the response ``id`` when it is a string."""
    response_id = data.get("id")
    return response_id if isinstance(response_id, str) else None


def parse_usage(usage_raw: Any) -> dict[str, int]:
    """Normalize a Chat Completions ``usage`` block into Pollux usage keys.

    Maps ``prompt_tokens``/``completion_tokens``/``total_tokens`` to
    ``input_tokens``/``output_tokens``/``total_tokens``, and surfaces
    ``reasoning_tokens`` and nested ``prompt_tokens_details.cached_tokens`` when
    present. Missing fields are simply omitted.
    """
    if not isinstance(usage_raw, Mapping):
        return {}
    usage: dict[str, int] = {}
    prompt = usage_raw.get("prompt_tokens")
    completion = usage_raw.get("completion_tokens")
    total = usage_raw.get("total_tokens")
    reasoning = usage_raw.get("reasoning_tokens")
    if isinstance(prompt, int):
        usage["input_tokens"] = prompt
    if isinstance(completion, int):
        usage["output_tokens"] = completion
    if isinstance(total, int):
        usage["total_tokens"] = total
    if isinstance(reasoning, int):
        usage["reasoning_tokens"] = reasoning
    details = usage_raw.get("prompt_tokens_details")
    if isinstance(details, Mapping):
        cached = details.get("cached_tokens")
        if isinstance(cached, int):
            usage["cached_tokens"] = cached
    return usage


def extract_error_message(response: httpx.Response) -> str:
    """Extract a useful error message from a Chat Completions HTTP error.

    Tries ``error.message``, then a top-level ``message``, then the raw response
    text, falling back to ``HTTP <status>``. Providers that nest upstream errors
    can check those first and delegate here for the common shape.
    """
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message
        message = payload.get("message")
        if isinstance(message, str) and message:
            return message
    text = response.text.strip()
    return text or f"HTTP {response.status_code}"


def normalize_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Pollux tool dicts to Chat Completions ``function`` tool format."""
    result: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            continue

        function: dict[str, Any] = {"name": name}
        description = tool.get("description")
        if isinstance(description, str) and description:
            function["description"] = description
        parameters = tool.get("parameters")
        if isinstance(parameters, dict):
            function["parameters"] = to_strict_schema(parameters)

        result.append({"type": "function", "function": function})
    return result


def map_tool_choice(
    tool_choice: str | dict[str, Any] | None,
) -> str | dict[str, Any] | None:
    """Map a Pollux ``tool_choice`` to the Chat Completions shape."""
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        return tool_choice
    if isinstance(tool_choice, dict) and isinstance(tool_choice.get("name"), str):
        return {
            "type": "function",
            "function": {"name": tool_choice["name"]},
        }
    return None


def parse_tool_calls(value: Any) -> list[ToolCall]:
    """Extract tool calls from a Chat Completions assistant message."""
    if not isinstance(value, list):
        return []

    tool_calls: list[ToolCall] = []
    for idx, item in enumerate(value):
        if not isinstance(item, Mapping):
            continue
        function = item.get("function")
        if not isinstance(function, Mapping):
            continue

        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue

        raw_arguments = function.get("arguments")
        if isinstance(raw_arguments, str):
            arguments = raw_arguments
        else:
            arguments = json.dumps(raw_arguments if raw_arguments is not None else {})

        raw_id = item.get("id")
        call_id = raw_id if isinstance(raw_id, str) and raw_id else f"call_{idx}"
        tool_calls.append(ToolCall(id=call_id, name=name, arguments=arguments))

    return tool_calls


def serialize_tool_calls(tool_calls: list[ToolCall] | None) -> list[dict[str, Any]]:
    """Serialize Pollux tool calls into the Chat Completions assistant shape."""
    if not tool_calls:
        return []

    return [
        {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": tool_call.arguments,
            },
        }
        for tool_call in tool_calls
    ]


def parse_sse_line(line: str) -> dict[str, Any] | None:
    """Parse one Server-Sent Events line into its JSON ``data`` object.

    Returns ``None`` for blank lines, non-``data:`` lines (comments/event names),
    the terminal ``[DONE]`` sentinel, and any ``data`` payload that is not a JSON
    object. Callers iterate ``response.aiter_lines()`` and skip ``None``.
    """
    stripped = line.strip()
    if not stripped.startswith("data:"):
        return None
    payload = stripped[len("data:") :].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def parse_chat_stream_chunk(data: Mapping[str, Any]) -> ProviderStreamChunk | None:
    """Map one OpenAI-compatible streaming ``data`` object to a stream chunk.

    Pulls visible text, model-native reasoning text, tool-call fragments, the
    finish reason, a streamed usage block, and the response id from one chunk.
    Returns ``None`` when the chunk carries nothing Pollux tracks (e.g. an empty
    role-priming delta) so the provider can skip it.
    """
    response_id = data.get("id")
    response_id = response_id if isinstance(response_id, str) and response_id else None

    text = ""
    reasoning = ""
    tool_calls: list[ToolCallDelta] = []
    finish_reason: str | None = None

    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
        choice = choices[0]
        delta = choice.get("delta")
        if isinstance(delta, Mapping):
            content = delta.get("content")
            if isinstance(content, str):
                text = content
            reasoning_content = delta.get("reasoning_content")
            if isinstance(reasoning_content, str):
                reasoning = reasoning_content
            tool_calls = _parse_tool_call_deltas(delta.get("tool_calls"))
        raw_finish = choice.get("finish_reason")
        if isinstance(raw_finish, str):
            finish_reason = raw_finish

    usage = parse_usage(data.get("usage")) or None

    if not (text or reasoning or tool_calls or finish_reason or usage or response_id):
        return None

    return ProviderStreamChunk(
        text=text,
        reasoning=reasoning,
        tool_calls=tuple(tool_calls),
        usage=usage,
        finish_reason=finish_reason,
        response_id=response_id,
    )


def _parse_tool_call_deltas(value: Any) -> list[ToolCallDelta]:
    """Extract streamed tool-call fragments from a chat-completions delta."""
    if not isinstance(value, list):
        return []

    deltas: list[ToolCallDelta] = []
    for position, item in enumerate(value):
        if not isinstance(item, Mapping):
            continue
        index = item.get("index")
        if not isinstance(index, int):
            index = position
        call_id = item.get("id")
        call_id = call_id if isinstance(call_id, str) and call_id else None
        name: str | None = None
        arguments = ""
        function = item.get("function")
        if isinstance(function, Mapping):
            raw_name = function.get("name")
            if isinstance(raw_name, str) and raw_name:
                name = raw_name
            raw_arguments = function.get("arguments")
            if isinstance(raw_arguments, str):
                arguments = raw_arguments
        deltas.append(
            ToolCallDelta(index=index, id=call_id, name=name, arguments=arguments)
        )
    return deltas
