"""Domain models for the provider transport layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pollux.interaction.tools import ToolCallDelta


@dataclass(frozen=True)
class ToolCall:
    """A tool call requested by the model."""

    id: str
    name: str
    arguments: str


def tool_call_to_dict(tool_call: ToolCall) -> dict[str, Any]:
    """Serialize a ToolCall to its normalized ``{id, name, arguments}`` dict.

    This is the single owner of the normalized tool-call dict shape shared by
    diagnostics (``raw_responses``), result envelopes, and conversation state.
    """
    return {
        "id": tool_call.id,
        "name": tool_call.name,
        "arguments": tool_call.arguments,
    }


@dataclass(frozen=True)
class ProviderFileAsset:
    """A formally tracked remote file asset returned by upload_file."""

    file_id: str
    provider: str
    mime_type: str
    file_name: str | None = None
    is_inline_fallback: bool = False


@dataclass(frozen=True)
class Message:
    """A standard conversational message turn."""

    role: str
    content: str = ""
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


def is_file_part(part: Any) -> bool:
    """Return True if *part* is a local-file placeholder awaiting upload.

    File placeholders are built from sources and resolved to provider assets
    during execution and deferred submission. This predicate is the single
    definition of that part shape.
    """
    return (
        isinstance(part, dict)
        and isinstance(part.get("file_path"), str)
        and isinstance(part.get("mime_type"), str)
    )


@dataclass
class ProviderResponse:
    """A standardized response from a provider generation call."""

    text: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    reasoning: str | None = None
    structured: dict[str, Any] | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    response_id: str | None = None
    finish_reason: str | None = None
    provider_state: dict[str, Any] | None = None
    artifacts: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProviderStreamChunk:
    """One normalized delta from a provider's streamed response.

    A provider's ``stream_generate`` yields these as it parses the upstream
    stream; core accumulates them into a final :class:`ProviderResponse` and maps
    them to the public event vocabulary. Every facet is optional so one upstream
    chunk can carry text, reasoning, tool-call fragments, usage, a finish reason,
    or a response id together.
    """

    text: str = ""
    reasoning: str = ""
    tool_calls: tuple[ToolCallDelta, ...] = ()
    usage: dict[str, int] | None = None
    finish_reason: str | None = None
    response_id: str | None = None


def provider_response_to_dict(response: ProviderResponse) -> dict[str, Any]:
    """Flatten a ProviderResponse into the normalized response dict shape.

    This is the single serialization form shared by execution diagnostics
    (``raw_responses``) and deferred item payloads. Optional facets are omitted
    when unset so the dict stays compact.
    """
    payload: dict[str, Any] = {"text": response.text, "usage": response.usage}
    if response.reasoning is not None:
        payload["reasoning"] = response.reasoning
    if response.structured is not None:
        payload["structured"] = response.structured
    if response.tool_calls is not None:
        payload["tool_calls"] = [tool_call_to_dict(tc) for tc in response.tool_calls]
    if response.response_id is not None:
        payload["response_id"] = response.response_id
    if response.finish_reason is not None:
        payload["finish_reason"] = response.finish_reason
    if response.provider_state is not None:
        payload["provider_state"] = response.provider_state
    if response.artifacts is not None:
        payload["artifacts"] = response.artifacts
    return payload
