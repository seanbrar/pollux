"""Stateless helpers for the OpenAI Chat Completions wire format.

Both the self-hosted ``local`` provider and the ``openrouter`` provider speak
OpenAI-compatible Chat Completions over httpx. The request shaping and input
handling differ (local is text-only; OpenRouter handles multimodal parts,
tools, and reasoning), but the primitives that read a Chat Completions *response*
are identical. This module owns that shared wire vocabulary so the two adapters
parse responses, usage, and errors one way.

These helpers are deliberately stateless and provider-neutral. Provider-specific
behavior (reasoning extraction, tool-call parsing, nested upstream errors) stays
in the adapters and layers on top of these primitives.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

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
