"""Portable transcript messages and opaque provider replay continuations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

from pollux.errors import ConfigurationError, PolluxError
from pollux.interaction.tools import ToolCall

if TYPE_CHECKING:
    from pollux.interaction.input import Input
    from pollux.providers.models import ProviderResponse


#: Bump when the serialized continuation shape or replay semantics change.
SCHEMA_VERSION = 2

MessageRole = Literal["user", "assistant", "tool"]
_MESSAGE_ROLES = {"user", "assistant", "tool"}


@dataclass(frozen=True, slots=True)
class Message:
    """A portable, application-authored text or tool transcript message."""

    role: MessageRole
    content: str = ""
    tool_calls: Sequence[ToolCall] = ()
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        """Freeze tool calls and reject shapes adapters cannot portably replay."""
        if self.role not in _MESSAGE_ROLES:
            raise ConfigurationError(
                f"Unsupported history message role: {self.role!r}",
                hint="Use 'user', 'assistant', or 'tool'. Put system instructions "
                "on Environment.instructions.",
            )
        if not isinstance(self.content, str):
            raise ConfigurationError(
                "Message content must be text",
                hint="Keep media in Source values or the current Input.",
            )
        calls = tuple(self.tool_calls)
        if not all(isinstance(call, ToolCall) for call in calls):
            raise ConfigurationError(
                "Message tool_calls must contain ToolCall values",
                hint="Normalize provider tool calls with ToolCall.from_text(...).",
            )
        if any(call.provider_state is not None for call in calls):
            raise ConfigurationError(
                "Portable history tool calls cannot contain provider state",
                hint="Rebuild transcript calls with ToolCall.from_text(...).",
            )
        object.__setattr__(self, "tool_calls", calls)

        if self.role == "user":
            if not self.content.strip():
                raise ConfigurationError("User history messages require non-empty text")
            if calls or self.tool_call_id is not None:
                raise ConfigurationError(
                    "User history messages cannot contain tool-call fields"
                )
        elif self.role == "assistant":
            if not self.content and not calls:
                raise ConfigurationError(
                    "Assistant history messages require text or tool calls"
                )
            if self.tool_call_id is not None:
                raise ConfigurationError(
                    "Assistant history messages cannot have tool_call_id"
                )
        else:
            if not isinstance(self.tool_call_id, str) or not self.tool_call_id.strip():
                raise ConfigurationError(
                    "Tool history messages require a non-empty tool_call_id"
                )
            if calls:
                raise ConfigurationError(
                    "Tool history messages cannot contain nested tool calls"
                )

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize this portable transcript message."""
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [call.to_jsonable() for call in self.tool_calls]
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        return payload

    @classmethod
    def from_jsonable(cls, data: Mapping[str, Any]) -> Message:
        """Parse and validate a portable transcript message."""
        role = data.get("role")
        if role not in _MESSAGE_ROLES:
            raise ConfigurationError(
                f"Unsupported history message role: {role!r}",
                hint="Use 'user', 'assistant', or 'tool'. Put system instructions "
                "on Environment.instructions.",
            )
        raw_calls = data.get("tool_calls")
        calls = _tool_calls_from_jsonable(raw_calls)
        content = data.get("content", "")
        if not isinstance(content, str):
            raise ConfigurationError("Message content must be text")
        tool_call_id = data.get("tool_call_id")
        return cls(
            role=cast("MessageRole", role),
            content=content,
            tool_calls=calls,
            tool_call_id=tool_call_id if isinstance(tool_call_id, str) else None,
        )

    @classmethod
    def from_openai(cls, data: Mapping[str, Any]) -> Message:
        """Build a portable message from one OpenAI Chat Completions message.

        System messages are intentionally rejected: stable system context belongs
        on :attr:`Environment.instructions`, not in portable turn history.
        """
        role = data.get("role")
        if role not in _MESSAGE_ROLES:
            raise ConfigurationError(
                f"Unsupported OpenAI history role: {role!r}; move system "
                "messages to Environment.instructions",
                hint="Move system messages to Environment.instructions.",
            )
        raw_calls = data.get("tool_calls")
        imported_calls = (
            tuple(
                ToolCall.from_openai(call)
                for call in raw_calls
                if isinstance(call, dict)
            )
            if isinstance(raw_calls, list)
            else ()
        )
        calls = tuple(
            ToolCall.from_text(
                id=call.id,
                name=call.name,
                arguments_text=call.arguments_text,
                index=call.index,
            )
            for call in imported_calls
        )
        tool_call_id = data.get("tool_call_id")
        return cls(
            role=cast("MessageRole", role),
            content=_openai_text_content(data.get("content")),
            tool_calls=calls,
            tool_call_id=tool_call_id if isinstance(tool_call_id, str) else None,
        )

    def to_openai(self) -> dict[str, Any]:
        """Serialize as one OpenAI Chat Completions transcript message."""
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [call.to_openai() for call in self.tool_calls]
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        return payload


@dataclass(frozen=True, slots=True)
class _ReplayMessage:
    """One internal continuation message, including opaque provider state."""

    role: MessageRole
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    provider_state: dict[str, Any] | None = None

    @classmethod
    def from_message(cls, message: Message) -> _ReplayMessage:
        return cls(
            role=message.role,
            content=message.content,
            tool_calls=tuple(message.tool_calls),
            tool_call_id=message.tool_call_id,
        )

    @classmethod
    def from_jsonable(cls, data: Mapping[str, Any]) -> _ReplayMessage:
        role = data.get("role")
        if role not in _MESSAGE_ROLES:
            raise PolluxError(
                f"Incompatible continuation message role: {role!r}",
                hint="Start a new interaction instead of editing continuation state.",
            )
        content = data.get("content", "")
        if not isinstance(content, str):
            raise PolluxError("Incompatible continuation message content")
        tool_call_id = data.get("tool_call_id")
        provider_state = data.get("provider_state")
        return cls(
            role=cast("MessageRole", role),
            content=content,
            tool_calls=_tool_calls_from_jsonable(data.get("tool_calls")),
            tool_call_id=tool_call_id if isinstance(tool_call_id, str) else None,
            provider_state=deepcopy(provider_state)
            if isinstance(provider_state, dict)
            else None,
        )

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [
                deepcopy(call.to_jsonable()) for call in self.tool_calls
            ]
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.provider_state is not None:
            payload["provider_state"] = deepcopy(self.provider_state)
        return payload


@dataclass(frozen=True, slots=True)
class _ContinuationState:
    messages: tuple[_ReplayMessage, ...]
    response_id: str | None
    provider: str
    provider_state: dict[str, Any] | None


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Continuation:
    """Opaque, serializable state for provider-correct replay.

    Applications receive this value from :attr:`Output.continuation`, persist it
    through :meth:`to_jsonable` / :meth:`from_jsonable`, and pass it back through
    ``Input(continuation=...)``. Replay fields are intentionally not public.
    """

    SCHEMA_VERSION: ClassVar[int] = SCHEMA_VERSION
    __state: _ContinuationState

    def __init__(self) -> None:
        raise TypeError(
            "Continuation values are created by Pollux outputs or "
            "Continuation.from_jsonable()"
        )

    def __repr__(self) -> str:
        """Return a representation that does not reveal replay state."""
        return f"Continuation(version={SCHEMA_VERSION})"

    def to_jsonable(self) -> dict[str, Any]:
        """Return a defensive JSON-compatible serialization of this handle."""
        state = self.__state
        payload: dict[str, Any] = {
            "version": SCHEMA_VERSION,
            "provider": state.provider,
            "messages": [message.to_jsonable() for message in state.messages],
        }
        if state.response_id is not None:
            payload["response_id"] = state.response_id
        if state.provider_state is not None:
            payload["provider_state"] = deepcopy(state.provider_state)
        return payload

    @classmethod
    def from_jsonable(
        cls,
        data: Mapping[str, Any],
        *,
        expected_provider: str | None = None,
    ) -> Continuation:
        """Restore a versioned artifact and optionally verify its provider."""
        version = data.get("version")
        if version != SCHEMA_VERSION:
            raise PolluxError(
                f"Incompatible continuation: expected schema version "
                f"{SCHEMA_VERSION}, got {version!r}",
                hint="This continuation was produced by a different Pollux "
                "version. Start a new interaction instead of reusing it.",
            )
        provider = data.get("provider")
        if not isinstance(provider, str) or not provider:
            raise PolluxError(
                "Incompatible continuation: missing provider identity",
                hint="Start a new interaction instead of editing continuation state.",
            )
        if expected_provider is not None and provider != expected_provider:
            raise PolluxError(
                f"Continuation provider {provider!r} does not match the active "
                f"provider {expected_provider!r}",
                hint="Reuse a continuation only with the provider that produced it.",
            )
        raw_messages = data.get("messages")
        if not isinstance(raw_messages, list):
            raise PolluxError("Incompatible continuation: messages must be a list")
        if not all(isinstance(message, Mapping) for message in raw_messages):
            raise PolluxError(
                "Incompatible continuation: every message must be an object"
            )
        response_id = data.get("response_id")
        provider_state = data.get("provider_state")
        return _new_continuation(
            messages=tuple(
                _ReplayMessage.from_jsonable(message) for message in raw_messages
            ),
            response_id=response_id if isinstance(response_id, str) else None,
            provider=provider,
            provider_state=deepcopy(provider_state)
            if isinstance(provider_state, dict)
            else None,
        )


def _new_continuation(
    *,
    messages: tuple[_ReplayMessage, ...],
    response_id: str | None,
    provider: str,
    provider_state: dict[str, Any] | None,
) -> Continuation:
    continuation = object.__new__(Continuation)
    object.__setattr__(
        continuation,
        "_Continuation__state",
        _ContinuationState(
            messages=messages,
            response_id=response_id,
            provider=provider,
            provider_state=deepcopy(provider_state),
        ),
    )
    return continuation


def _continuation_state(continuation: Continuation) -> _ContinuationState:
    """Return opaque replay state for Pollux internals."""
    return cast(
        "_ContinuationState",
        object.__getattribute__(continuation, "_Continuation__state"),
    )


def _tool_calls_from_jsonable(raw: Any) -> tuple[ToolCall, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(
        ToolCall.from_text(
            id=str(call.get("id", "")),
            name=str(call.get("name", "")),
            arguments_text=str(call.get("arguments_text", "")),
            index=call.get("index") if isinstance(call.get("index"), int) else None,
            provider_state=deepcopy(call.get("provider_state"))
            if isinstance(call.get("provider_state"), dict)
            else None,
        )
        for call in raw
        if isinstance(call, dict)
    )


def _openai_text_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n\n".join(
            part["text"]
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return str(content)


def _prior_messages(input: Input) -> tuple[_ReplayMessage, ...]:  # noqa: A002
    if input.continuation is not None:
        prior = _continuation_state(input.continuation).messages
    elif input.history is not None:
        prior = tuple(_ReplayMessage.from_message(message) for message in input.history)
    else:
        prior = ()
    tool_messages = tuple(
        _ReplayMessage(role="tool", content=result.content, tool_call_id=result.call_id)
        for result in input.tool_results
    )
    return prior + tool_messages


def build_continuation(
    input: Input,  # noqa: A002
    response: ProviderResponse,
    *,
    user_content: str | None,
    provider: str | None,
) -> Continuation | None:
    """Assemble the next opaque continuation after a successful interaction."""
    wants_conversation = input.continuation is not None or input.history is not None
    response_tool_calls = response.tool_calls or ()
    if not (wants_conversation or response_tool_calls):
        return None
    if provider is None:
        raise PolluxError("Cannot create a continuation without provider identity")

    messages = list(_prior_messages(input))
    turn_user_content = user_content or input.content
    if turn_user_content is not None:
        messages.append(_ReplayMessage(role="user", content=turn_user_content))

    provider_state = (
        deepcopy(response.provider_state)
        if isinstance(response.provider_state, dict)
        else None
    )
    messages.append(
        _ReplayMessage(
            role="assistant",
            content=response.text,
            tool_calls=tuple(
                ToolCall.from_text(
                    id=call.id,
                    name=call.name,
                    arguments_text=call.arguments,
                )
                for call in response_tool_calls
            ),
            provider_state=provider_state,
        )
    )
    response_id = (
        response.response_id if isinstance(response.response_id, str) else None
    )
    return _new_continuation(
        messages=tuple(messages),
        response_id=response_id,
        provider=provider,
        provider_state=provider_state,
    )
