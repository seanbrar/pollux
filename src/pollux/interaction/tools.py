"""Tool declaration, call, and result primitives for the v2 interaction model.

These are provider-neutral. A :class:`ToolDeclaration` describes a function the
model may request; a :class:`ToolCall` is a normalized request the model emitted;
a :class:`ToolResult` is application-produced output for a prior call. None of
them execute anything — applications own tool execution and policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import TYPE_CHECKING, Any

from pollux.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Mapping

#: A parsed JSON value, as produced by :func:`json.loads`.
JSONValue = dict[str, Any] | list[Any] | str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class ToolDeclaration:
    """A provider-neutral description of a tool the model may request."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    strict: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ToolDeclaration:
        """Build a declaration from a flat or OpenAI-style ``function`` dict."""
        payload: Mapping[str, Any] = data
        nested = data.get("function")
        if isinstance(nested, dict):
            payload = nested
        name = payload.get("name")
        if not isinstance(name, str) or not name:
            raise ConfigurationError(
                "tool declaration requires a non-empty 'name'",
                hint="Pass {'name': 'get_weather', 'description': ..., "
                "'parameters': {...}}.",
            )
        description = payload.get("description", "")
        parameters = payload.get("parameters", {})
        strict = payload.get("strict", True)
        return cls(
            name=name,
            description=str(description) if description is not None else "",
            parameters=dict(parameters) if isinstance(parameters, dict) else {},
            strict=strict if isinstance(strict, bool) else True,
        )


def _parse_arguments(arguments_text: str) -> tuple[JSONValue, str | None]:
    """Parse a raw provider argument string once.

    Returns the parsed value and ``None`` on success, or ``(None, message)``
    when the text is not valid JSON. An empty string parses to ``None`` without
    being treated as an error.
    """
    if arguments_text == "":
        return None, None
    try:
        return json.loads(arguments_text), None
    except (json.JSONDecodeError, ValueError) as exc:
        return None, str(exc)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A normalized tool request emitted by the model.

    ``arguments_text`` is the exact raw provider argument string (after any
    stream fragments are assembled). ``arguments`` is the parsed JSON; when the
    text is not valid JSON it is ``None`` and ``arguments_error`` explains why.
    This preserves both convenience and recoverability.
    """

    id: str
    name: str
    arguments_text: str = ""
    arguments: JSONValue = None
    arguments_error: str | None = None
    index: int | None = None
    provider_state: dict[str, Any] | None = None

    @classmethod
    def from_text(
        cls,
        *,
        id: str,  # noqa: A002 - mirrors the public ToolCall.id field name
        name: str,
        arguments_text: str = "",
        index: int | None = None,
        provider_state: dict[str, Any] | None = None,
    ) -> ToolCall:
        """Build a call from raw provider fields, parsing arguments once."""
        arguments, arguments_error = _parse_arguments(arguments_text)
        return cls(
            id=id,
            name=name,
            arguments_text=arguments_text,
            arguments=arguments,
            arguments_error=arguments_error,
            index=index,
            provider_state=provider_state,
        )

    def arguments_dict(self) -> dict[str, Any]:
        """Return parsed JSON-object arguments or raise an explicit config error.

        Agent loops usually dispatch tools from object-shaped JSON arguments.
        This helper keeps that path strict: malformed JSON and non-object JSON
        are rejected instead of being silently treated as an empty dict.
        """
        if self.arguments_error is not None:
            raise ConfigurationError(
                f"Tool call {self.name!r} has invalid JSON arguments",
                hint=self.arguments_error,
            )
        if self.arguments is None:
            return {}
        if not isinstance(self.arguments, dict):
            raise ConfigurationError(
                f"Tool call {self.name!r} arguments must be a JSON object",
                hint="Define tool parameters as an object schema and retry the turn.",
            )
        return dict(self.arguments)

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize to a compact JSON-compatible dict (optional facets omitted)."""
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "arguments_text": self.arguments_text,
        }
        if self.arguments_error is not None:
            payload["arguments_error"] = self.arguments_error
        if self.index is not None:
            payload["index"] = self.index
        if self.provider_state is not None:
            payload["provider_state"] = self.provider_state
        return payload


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    """One incremental fragment of a streamed tool call.

    Providers stream tool calls in pieces: an opening fragment usually carries
    ``id`` and ``name`` for a slot, and later fragments append ``arguments``
    text. ``index`` identifies the call slot so fragments reassemble in order.
    Core accumulates these into a final :class:`ToolCall`; consumers that only
    want completed calls can ignore ``tool_call_delta`` events.
    """

    index: int = 0
    id: str | None = None
    name: str | None = None
    arguments: str = ""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Application-produced output returned to the model for a prior tool call."""

    call_id: str
    content: str
    is_error: bool = False

    @classmethod
    def from_value(
        cls,
        *,
        call_id: str,
        value: JSONValue,
        is_error: bool = False,
    ) -> ToolResult:
        """Build a tool result from a JSON value, serializing non-strings.

        Strings are preserved as-is. Other JSON values are encoded compactly so
        agent loops can return structured tool output without repeating
        ``json.dumps`` at every dispatch site.
        """
        if isinstance(value, str):
            content = value
        else:
            try:
                content = json.dumps(value, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError) as exc:
                raise ConfigurationError(
                    "ToolResult.from_value() requires a JSON-serializable value",
                    hint="Return a string, dict, list, number, boolean, or None.",
                ) from exc
        return cls(call_id=call_id, content=content, is_error=is_error)

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        payload: dict[str, Any] = {"call_id": self.call_id, "content": self.content}
        if self.is_error:
            payload["is_error"] = True
        return payload
