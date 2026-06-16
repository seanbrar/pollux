"""The v2 ``Continuation`` primitive and its typed replay messages.

``Continuation`` is the public, serializable state Pollux needs to continue a
provider-correct interaction. It replaces v1.x's private ``_conversation_state``
dict. It is not memory: Pollux does not summarize, rank, or compact it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from pollux.errors import PolluxError
from pollux.interaction.tools import ToolCall

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Bump when the serialized shape changes incompatibly.
SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Message:
    """A typed conversational turn preserved for provider-correct replay."""

    role: str
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    provider_state: dict[str, Any] | None = None

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize to a compact JSON-compatible dict (optional facets omitted)."""
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [tc.to_jsonable() for tc in self.tool_calls]
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.provider_state is not None:
            payload["provider_state"] = self.provider_state
        return payload

    @classmethod
    def from_jsonable(cls, data: Mapping[str, Any]) -> Message:
        """Parse a serialized message, type-guarding each facet."""
        raw_tool_calls = data.get("tool_calls")
        tool_calls: tuple[ToolCall, ...] = ()
        if isinstance(raw_tool_calls, list):
            tool_calls = tuple(
                ToolCall.from_text(
                    id=str(tc.get("id", "")),
                    name=str(tc.get("name", "")),
                    arguments_text=str(tc.get("arguments_text", "")),
                    index=tc.get("index") if isinstance(tc.get("index"), int) else None,
                    provider_state=tc.get("provider_state")
                    if isinstance(tc.get("provider_state"), dict)
                    else None,
                )
                for tc in raw_tool_calls
                if isinstance(tc, dict)
            )
        content = data.get("content", "")
        tool_call_id = data.get("tool_call_id")
        provider_state = data.get("provider_state")
        return cls(
            role=str(data.get("role", "user")),
            content=content if isinstance(content, str) else str(content),
            tool_calls=tool_calls,
            tool_call_id=tool_call_id if isinstance(tool_call_id, str) else None,
            provider_state=provider_state if isinstance(provider_state, dict) else None,
        )


@dataclass(frozen=True, slots=True)
class Continuation:
    """Serializable state for continuing a provider-correct interaction.

    Read it from ``output.continuation`` and pass it back as
    ``Input(continuation=...)`` to take the next turn. Persist it across processes
    with :meth:`to_jsonable` / :meth:`from_jsonable`, which stamp and verify a
    schema version (and, optionally, the producing provider).

    A continuation is bound to the provider that produced it — its
    ``provider_state`` (response ids, provider-specific replay blocks) is not
    portable. Reusing one under a different provider is rejected before dispatch.
    It is not memory: Pollux does not summarize, rank, or compact it.
    """

    SCHEMA_VERSION: ClassVar[int] = SCHEMA_VERSION

    messages: tuple[Message, ...] = ()
    response_id: str | None = None
    provider: str | None = None
    provider_state: dict[str, Any] | None = None
    version: int = SCHEMA_VERSION

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict with version/provider markers."""
        payload: dict[str, Any] = {
            "version": self.version,
            "messages": [m.to_jsonable() for m in self.messages],
        }
        if self.provider is not None:
            payload["provider"] = self.provider
        if self.response_id is not None:
            payload["response_id"] = self.response_id
        if self.provider_state is not None:
            payload["provider_state"] = self.provider_state
        return payload

    @classmethod
    def from_jsonable(
        cls,
        data: Mapping[str, Any],
        *,
        expected_provider: str | None = None,
    ) -> Continuation:
        """Parse a serialized continuation, rejecting incompatible artifacts.

        A continuation written by an incompatible schema version is refused with
        a clear error rather than misread. When *expected_provider* is given, a
        continuation produced by a different provider is also refused.
        """
        raw_version = data.get("version")
        version = raw_version if isinstance(raw_version, int) else None
        if version != SCHEMA_VERSION:
            raise PolluxError(
                f"Incompatible continuation: expected schema version "
                f"{SCHEMA_VERSION}, got {version!r}",
                hint="This continuation was produced by a different Pollux "
                "version. Start a new interaction instead of reusing it.",
            )
        provider = data.get("provider")
        provider = provider if isinstance(provider, str) else None
        if expected_provider is not None and provider != expected_provider:
            raise PolluxError(
                f"Continuation provider {provider!r} does not match the active "
                f"provider {expected_provider!r}",
                hint="Reuse a continuation only with the provider that produced it.",
            )
        raw_messages = data.get("messages")
        messages: tuple[Message, ...] = ()
        if isinstance(raw_messages, list):
            messages = tuple(
                Message.from_jsonable(m) for m in raw_messages if isinstance(m, dict)
            )
        response_id = data.get("response_id")
        provider_state = data.get("provider_state")
        return cls(
            messages=messages,
            response_id=response_id if isinstance(response_id, str) else None,
            provider=provider,
            provider_state=provider_state if isinstance(provider_state, dict) else None,
            version=version,
        )
