"""Thin engine for store-backed conversation operations.

Provides a simple façade that loads state from a `ConversationStore`,
executes a prompt via the `Conversation` extension, and appends the
result using optimistic concurrency control.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from .conversation import Conversation

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from pollux.core.types import InitialCommand, ResultEnvelope

    from .conversation_store import ConversationStore
    from .conversation_types import ConversationState, Exchange

    class ExecutorLike(Protocol):
        """Minimal executor protocol used by the engine."""

        config: Any

        def execute(self, _command: InitialCommand) -> Awaitable[ResultEnvelope]:
            """Execute a command and return a typed result envelope."""
            ...


class ConversationEngine:
    """Engine orchestrating store I/O with conversation execution."""

    def __init__(self, executor: ExecutorLike, store: ConversationStore) -> None:
        """Initialize the engine with an executor and a store."""
        self._executor = executor
        self._store = store

    async def ask(self, conversation_id: str, prompt: str) -> Exchange:
        """Load, execute one prompt, and append the resulting exchange.

        Args:
            conversation_id: Persistent conversation identifier.
            prompt: User prompt to execute.

        Returns:
            The newly appended `Exchange`.
        """
        state: ConversationState = await self._store.load(conversation_id)
        conv = Conversation(state, self._executor)
        conv2 = await conv.ask(prompt)
        # OCC append (store enforces expected_version)
        await self._store.append(
            conversation_id, expected_version=state.version, ex=conv2.state.turns[-1]
        )
        return conv2.state.turns[-1]
