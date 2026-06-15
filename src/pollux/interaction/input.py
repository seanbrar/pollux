"""``Input``: the per-interaction payload asking the model for one response.

An :class:`Input` represents exactly one model turn. Agent loops are repeated
inputs over a stable or evolving environment. Prior turn state arrives either as
explicit ``history`` or as a ``continuation`` from a previous output — not both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pollux.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pollux.interaction.continuation import Continuation, Message
    from pollux.interaction.tools import ToolResult


@dataclass(frozen=True, slots=True)
class Input:
    """One model turn: user content plus optional prior state and tool results.

    ``history`` and ``tool_results`` accept any ordered sequence and are frozen
    to tuples.
    """

    content: str | None = None
    history: Sequence[Message] | None = None
    continuation: Continuation | None = None
    tool_results: Sequence[ToolResult] = ()

    def __post_init__(self) -> None:
        """Coerce sequences to tuples and validate the turn is well formed."""
        if self.history is not None:
            object.__setattr__(self, "history", tuple(self.history))
        object.__setattr__(self, "tool_results", tuple(self.tool_results))

        if self.history is not None and self.continuation is not None:
            raise ConfigurationError(
                "history and continuation are mutually exclusive",
                hint="Use exactly one prior-turn state source per interaction.",
            )

        has_content = bool(self.content and self.content.strip())
        if not has_content and not self.tool_results:
            raise ConfigurationError(
                "Input has no user content and no tool results",
                hint="Provide content for a new turn, or tool_results to "
                "continue from prior tool calls.",
            )
