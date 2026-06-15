"""Compile v2 interaction primitives into a provider request.

This is the v2 boundary's request-compilation step. It maps an immutable
``EnvironmentSnapshot`` + per-turn ``Input`` + ``OutputRequirements`` into the
provider transport's ``ProviderRequest``. Keeping ``ProviderRequest`` as the
internal compile artifact lets the existing, battle-tested adapter translation be
reused unchanged while core speaks the v2 model.

File placeholders in ``parts`` are resolved to provider assets later, by the v2
execution path's core-orchestrated upload step (see ``interaction/execute.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pollux.plan import build_shared_parts
from pollux.providers.models import (
    Message as ProviderMessage,
)
from pollux.providers.models import (
    ProviderRequest,
)
from pollux.providers.models import (
    ToolCall as ProviderToolCall,
)

if TYPE_CHECKING:
    from pollux.config import Config
    from pollux.interaction.continuation import Message
    from pollux.interaction.environment import EnvironmentSnapshot
    from pollux.interaction.input import Input
    from pollux.interaction.requirements import OutputRequirements
    from pollux.interaction.tools import ToolResult


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


def _resolve_prior_turns(
    input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
) -> tuple[list[ProviderMessage], str | None, dict[str, object] | None]:
    """Resolve replay messages, response id, and provider state from an input.

    Continuation and explicit history are alternative prior-state sources
    (``Input`` already enforces they are not both set). Per-message provider
    state is folded under a ``"history"`` key so the transport can replay opaque
    blocks (e.g. reasoning) the same way the v1 path does.
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


def compile_request(
    snapshot: EnvironmentSnapshot,
    input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
    requirements: OutputRequirements,
    config: Config,
    *,
    cache_name: str | None = None,
    implicit_caching: bool = False,
) -> ProviderRequest:
    """Compile v2 primitives into a ``ProviderRequest`` (file parts unresolved)."""
    shared_parts = (
        []
        if cache_name is not None
        else build_shared_parts(snapshot.sources, provider=config.provider)
    )
    parts = (
        [*shared_parts, input.content] if input.content is not None else shared_parts
    )

    tools = [
        {
            "name": decl.name,
            "description": decl.description,
            "parameters": decl.parameters,
        }
        for decl in snapshot.tools
    ] or None

    history, previous_response_id, provider_state = _resolve_prior_turns(input)

    return ProviderRequest(
        model=config.model,
        parts=parts,
        system_instruction=snapshot.instructions,
        cache_name=cache_name,
        response_schema=requirements.output_schema_json(),
        temperature=requirements.temperature,
        top_p=requirements.top_p,
        tools=tools,
        tool_choice=requirements.tool_choice,
        reasoning_effort=requirements.reasoning_effort,
        reasoning_budget_tokens=requirements.reasoning_budget_tokens,
        history=history or None,
        previous_response_id=previous_response_id,
        provider_state=provider_state,
        max_tokens=requirements.max_tokens,
        implicit_caching=implicit_caching,
        provider_options=requirements.provider_options_for(config.provider),
    )
