"""Shared compilation helpers for provider adapters.

Adapters own how a v2 interaction is shaped for their upstream SDK. These
helpers cover the generic, provider-neutral pieces — assembling request parts
from the prepared environment plus the turn input, honoring a persistent cache,
and translating prior-turn state into transport messages — so each adapter reads
the canonical primitives (``EnvironmentSnapshot`` / ``Input`` /
``OutputRequirements``) directly instead of a shared kitchen-sink request object.

The environment's source parts are uploaded and frozen onto the snapshot by the
core execution path before ``generate`` is called, so adapters never perform
source uploads themselves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pollux.providers.models import (
    Message as ProviderMessage,
)
from pollux.providers.models import (
    ToolCall as ProviderToolCall,
)

if TYPE_CHECKING:
    from pollux.interaction.continuation import Message
    from pollux.interaction.environment import EnvironmentSnapshot
    from pollux.interaction.input import Input
    from pollux.interaction.tools import ToolResult


def request_parts(
    snapshot: EnvironmentSnapshot,
    input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
) -> list[Any]:
    """Prepared shared source parts (uploaded by core) plus this turn's content.

    When the environment uses a persistent cache, ``prepared_parts`` is empty
    because the sources are baked into the cache.
    """
    parts = list(snapshot.prepared_parts or ())
    if input.content is not None:
        parts.append(input.content)
    return parts


def system_instruction(snapshot: EnvironmentSnapshot) -> str | None:
    """System instruction, suppressed when baked into a persistent cache."""
    return None if snapshot.cache_name else snapshot.instructions


def tool_dicts(snapshot: EnvironmentSnapshot) -> list[dict[str, Any]] | None:
    """Normalized tool dicts, suppressed when baked into a persistent cache.

    Returns the provider-neutral ``{name, description, parameters, strict}`` shape; each
    adapter translates that into its own SDK tool schema.
    """
    if snapshot.cache_name:
        return None
    return [
        {
            "name": decl.name,
            "description": decl.description,
            "parameters": decl.parameters,
            "strict": decl.strict,
        }
        for decl in snapshot.tools
    ] or None


def _provider_message(message: Message) -> ProviderMessage:
    """Translate a v2 replay ``Message`` into a transport ``Message``."""
    tool_calls = [
        ProviderToolCall(id=tc.id, name=tc.name, arguments=tc.arguments_text)
        for tc in message.tool_calls
    ] or None
    return ProviderMessage(
        role=message.role,
        content=message.content,
        tool_call_id=message.tool_call_id,
        tool_calls=tool_calls,
    )


def _tool_result_message(tool_result: ToolResult) -> ProviderMessage:
    """Represent an application tool result as a tool-role replay message."""
    return ProviderMessage(
        role="tool",
        content=tool_result.content,
        tool_call_id=tool_result.call_id,
    )


def prior_turns(
    input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
) -> tuple[list[ProviderMessage], str | None, dict[str, object] | None]:
    """Resolve replay messages, response id, and provider state from an input.

    Continuation and explicit history are alternative prior-state sources
    (``Input`` already enforces they are not both set). Per-message provider
    state is folded under a ``"history"`` key so the transport can replay opaque
    blocks (e.g. reasoning) during continuation.
    """
    prior: tuple[Message, ...] = ()
    previous_response_id: str | None = None
    provider_state: dict[str, object] | None = None

    if input.continuation is not None:
        prior = input.continuation.messages
        previous_response_id = input.continuation.response_id
        if input.continuation.provider_state is not None:
            provider_state = dict(input.continuation.provider_state)
    elif input.history is not None:
        prior = tuple(input.history)

    messages = [_provider_message(m) for m in prior]
    item_states: list[dict[str, object] | None] = [
        dict(m.provider_state) if m.provider_state is not None else None for m in prior
    ]
    messages.extend(_tool_result_message(tr) for tr in input.tool_results)

    if any(state is not None for state in item_states):
        provider_state = provider_state or {}
        provider_state["history"] = item_states

    return messages, previous_response_id, provider_state
