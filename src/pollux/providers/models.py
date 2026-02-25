"""Domain models for the provider transport layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ToolCall:
    """A tool call requested by the model."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Message:
    """A standard conversational message turn."""

    role: str
    content: str = ""
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


@dataclass(frozen=True)
class ProviderRequest:
    """A unified request payload for a provider generation call."""

    model: str
    parts: list[Any]
    system_instruction: str | None = None
    cache_name: str | None = None
    response_schema: dict[str, Any] | None = None
    temperature: float | None = None
    top_p: float | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Literal["auto", "required", "none"] | dict[str, Any] | None = None
    reasoning_effort: str | None = None
    history: list[Message] | None = None
    previous_response_id: str | None = None


@dataclass
class ProviderResponse:
    """A standardized response from a provider generation call."""

    text: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    reasoning: str | None = None
    structured: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    response_id: str | None = None
