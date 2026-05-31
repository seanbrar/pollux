"""The v1.x conversation-continuation mechanism.

Pollux 1.x carries continuation state as a dict under the private
``_conversation_state`` key of a ``ResultEnvelope``. This module owns the full
surface of that mechanism:

- :class:`ConversationState` owns the serialized ``_conversation_state`` shape.
- :func:`load_continuation` resolves prior-turn state from ``continue_from``.
- :func:`history_to_messages` translates history dicts into provider messages.
- :func:`build_conversation_state` assembles the updated state after a response.
- :func:`history_text_from_parts` derives a replayable user text turn.

It is the single seam the v2 ``Continuation`` primitive will replace.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING, Any, ClassVar

from pollux.errors import ConfigurationError
from pollux.providers.models import Message, ToolCall, tool_call_to_dict

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pollux.options import Options
    from pollux.providers.models import ProviderResponse


@dataclass(frozen=True)
class ConversationState:
    """Serialized state stored under a ResultEnvelope's ``_conversation_state`` key.

    This is the single owner of that dict shape: the magic keys (``history``,
    ``response_id``, ``provider_state``) and the envelope key itself live here
    rather than as string literals across the read, write, and continue paths.
    It is distinct from :class:`ContinuationState`, which is the *resolved*
    prior-turn working state derived from this serialized form.
    """

    #: Envelope key under which this state is stored in a ``ResultEnvelope``.
    ENVELOPE_KEY: ClassVar[str] = "_conversation_state"

    history: list[dict[str, Any]]
    response_id: str | None = None
    provider_state: dict[str, Any] | None = None

    @classmethod
    def from_envelope(cls, envelope: Mapping[str, Any]) -> ConversationState | None:
        """Parse from a ResultEnvelope, or ``None`` when the key is absent/invalid."""
        state = envelope.get(cls.ENVELOPE_KEY)
        if not isinstance(state, dict):
            return None
        return cls.from_state_dict(state)

    @classmethod
    def from_state_dict(cls, state: Mapping[str, Any]) -> ConversationState:
        """Parse a serialized state dict, type-guarding each facet."""
        raw_history = state.get("history")
        history = list(raw_history) if isinstance(raw_history, list) else []
        raw_response_id = state.get("response_id")
        response_id = raw_response_id if isinstance(raw_response_id, str) else None
        raw_provider_state = state.get("provider_state")
        provider_state = (
            dict(raw_provider_state) if isinstance(raw_provider_state, dict) else None
        )
        return cls(
            history=history,
            response_id=response_id,
            provider_state=provider_state,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the ``_conversation_state`` dict shape.

        Optional facets are omitted when unset so the shape stays compact and
        matches what ``build_conversation_state`` has always produced.
        """
        state: dict[str, Any] = {"history": self.history}
        if self.provider_state is not None:
            state["provider_state"] = self.provider_state
        if self.response_id is not None:
            state["response_id"] = self.response_id
        return state


@dataclass(frozen=True)
class ContinuationState:
    """Resolved prior-turn state for the current interaction.

    ``history`` is the effective message history (explicit or recovered from
    ``continue_from``). ``conversation_history`` is the base history that the
    updated state will be appended to.
    """

    history: list[dict[str, Any]] | None
    conversation_history: list[dict[str, Any]]
    previous_response_id: str | None
    provider_state: dict[str, Any] | None


def load_continuation(options: Options) -> ContinuationState:
    """Resolve prior conversation state from ``history`` / ``continue_from``."""
    history = options.history
    conversation_history: list[dict[str, Any]] = []
    if history is not None:
        conversation_history = [dict(item) for item in history]

    previous_response_id: str | None = None
    provider_state: dict[str, Any] | None = None
    if options.continue_from is not None:
        state = ConversationState.from_envelope(options.continue_from)
        if state is None:
            raise ConfigurationError(
                "continue_from is missing _conversation_state",
                hint=(
                    "Pass a prior Pollux ResultEnvelope produced with conversation "
                    "support."
                ),
            )

        if history is None:
            conversation_history = [
                item
                for item in state.history
                if isinstance(item, dict) and isinstance(item.get("role"), str)
            ]
            history = conversation_history

        previous_response_id = state.response_id
        provider_state = state.provider_state

    return ContinuationState(
        history=history,
        conversation_history=conversation_history,
        previous_response_id=previous_response_id,
        provider_state=provider_state,
    )


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


def history_to_messages(
    history: list[dict[str, Any]],
) -> tuple[list[Message], list[dict[str, Any] | None] | None]:
    """Translate history dicts into provider ``Message`` objects.

    Returns the messages plus the per-message provider states when any are
    present (so the caller can fold them into the request provider state under
    a ``"history"`` key), or ``None`` when no message carried provider state.
    """
    messages: list[Message] = []
    item_states: list[dict[str, Any] | None] = []
    has_item_states = False
    for h in history:
        role = h.get("role", "user")
        content = h.get("content", "")
        tc_id = h.get("tool_call_id")
        msg_provider_state = h.get("provider_state")
        tcs = None
        raw_tcs = h.get("tool_calls")
        if isinstance(raw_tcs, list):
            tcs = []
            for tc in raw_tcs:
                if isinstance(tc, dict):
                    raw_args = tc.get("arguments", "")
                    args_str = (
                        json.dumps(raw_args)
                        if isinstance(raw_args, dict)
                        else str(raw_args)
                    )
                    tcs.append(
                        ToolCall(
                            id=str(tc.get("id", "")),
                            name=str(tc.get("name", "")),
                            arguments=args_str,
                        )
                    )
        if isinstance(msg_provider_state, dict):
            item_states.append(dict(msg_provider_state))
            has_item_states = True
        else:
            item_states.append(None)
        messages.append(
            Message(
                role=str(role),
                content=content if isinstance(content, str) else str(content),
                tool_call_id=tc_id if isinstance(tc_id, str) else None,
                tool_calls=tcs,
            )
        )
    return messages, (item_states if has_item_states else None)


def build_conversation_state(
    responses: list[ProviderResponse],
    *,
    first_prompt: str | None,
    first_user_content: str | None,
    conversation_history: list[dict[str, Any]],
    previous_response_id: str | None,
    wants_conversation: bool,
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
    ).to_dict()
