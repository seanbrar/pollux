"""Conversation-continuation serialization.

``ConversationState`` owns the serialized conversation-state dict shape: the
magic keys (``version``, ``provider``, ``history``, ``response_id``,
``provider_state``). The v2 :class:`~pollux.interaction.continuation.Continuation`
primitive is converted to and from this shape in ``interaction/adapters.py``.

- :class:`ConversationState` owns the serialized state shape.
- :func:`build_conversation_state` assembles the updated state after a response.
- :func:`history_text_from_parts` derives a replayable user text turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from pollux.providers.models import tool_call_to_dict

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pollux.providers.models import ProviderResponse


@dataclass(frozen=True)
class ConversationState:
    """The single owner of the serialized conversation-state dict shape.

    The magic keys (``version``, ``provider``, ``history``, ``response_id``,
    ``provider_state``) live here rather than as string literals across the
    read, write, and continue paths.

    The ``version`` and ``provider`` markers let a future major (which redefines
    this shape) detect and reject an incompatible serialized state with a clear
    error instead of misreading it. Reads stay permissive: a missing
    ``version`` is treated as a pre-1.8 state rather than an error.
    """

    #: Schema version stamped into newly written state. Bump on shape changes.
    SCHEMA_VERSION: ClassVar[int] = 1

    history: list[dict[str, Any]]
    response_id: str | None = None
    provider_state: dict[str, Any] | None = None
    version: int = SCHEMA_VERSION
    provider: str | None = None

    @classmethod
    def from_state_dict(cls, state: Mapping[str, Any]) -> ConversationState:
        """Parse a serialized state dict, type-guarding each facet.

        A missing or non-integer ``version`` is read as ``1`` (a pre-1.8
        state), keeping older serialized state loadable.
        """
        raw_history = state.get("history")
        history = list(raw_history) if isinstance(raw_history, list) else []
        raw_response_id = state.get("response_id")
        response_id = raw_response_id if isinstance(raw_response_id, str) else None
        raw_provider_state = state.get("provider_state")
        provider_state = (
            dict(raw_provider_state) if isinstance(raw_provider_state, dict) else None
        )
        raw_version = state.get("version")
        version = raw_version if isinstance(raw_version, int) else 1
        raw_provider = state.get("provider")
        provider = raw_provider if isinstance(raw_provider, str) else None
        return cls(
            history=history,
            response_id=response_id,
            provider_state=provider_state,
            version=version,
            provider=provider,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the ``_conversation_state`` dict shape.

        Optional facets are omitted when unset so the shape stays compact and
        matches what ``build_conversation_state`` has always produced.
        """
        state: dict[str, Any] = {"version": self.version, "history": self.history}
        if self.provider is not None:
            state["provider"] = self.provider
        if self.provider_state is not None:
            state["provider_state"] = self.provider_state
        if self.response_id is not None:
            state["response_id"] = self.response_id
        return state


def history_text_from_parts(parts: list[Any]) -> str | None:
    """Return a replayable text history message when all parts are text."""
    texts: list[str] = []
    for part in parts:
        if isinstance(part, str):
            texts.append(part)
            continue
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                texts.append(text)
                continue
        return None
    return "\n\n".join(texts) if texts else None


def build_conversation_state(
    responses: list[ProviderResponse],
    *,
    first_prompt: str | None,
    first_user_content: str | None,
    conversation_history: list[dict[str, Any]],
    previous_response_id: str | None,
    wants_conversation: bool,
    provider: str | None = None,
) -> dict[str, Any] | None:
    """Assemble updated ``_conversation_state`` after a response.

    Built when the caller opted into conversation continuity, or when the
    response carries tool calls the caller may need to continue. Returns
    ``None`` when neither applies.
    """
    has_tool_calls = bool(responses and responses[0].tool_calls)
    if not ((wants_conversation or has_tool_calls) and responses):
        return None

    prompt = (
        first_prompt
        if isinstance(first_prompt, str)
        else str(first_prompt)
        if first_prompt is not None
        else None
    )
    user_content = first_user_content or prompt
    assistant_msg: dict[str, Any] = {
        "role": "assistant",
        "content": responses[0].text,
    }
    tool_calls = responses[0].tool_calls
    if tool_calls:
        assistant_msg["tool_calls"] = [tool_call_to_dict(tc) for tc in tool_calls]
    provider_msg_state = responses[0].provider_state
    if isinstance(provider_msg_state, dict):
        assistant_msg["provider_state"] = provider_msg_state

    updated_history: list[dict[str, Any]] = [*conversation_history]
    if user_content is not None:
        updated_history.append({"role": "user", "content": user_content})
    updated_history.append(assistant_msg)

    response_id = responses[0].response_id
    return ConversationState(
        history=updated_history,
        response_id=response_id
        if isinstance(response_id, str)
        else previous_response_id,
        provider_state=(
            provider_msg_state if isinstance(provider_msg_state, dict) else None
        ),
        provider=provider,
    ).to_dict()
