"""Single-turn data structures for request/response history.

This module deliberately models only a single exchange (a "turn").
Multi-turn conversations live in the official extension under
`pollux.extensions.conversation`.
"""

from __future__ import annotations

import dataclasses

from ._validation import _require


@dataclasses.dataclass(frozen=True, slots=True)
class Turn:
    """A single request/response exchange."""

    question: str
    answer: str
    is_error: bool = False

    def __post_init__(self) -> None:
        """Validate invariants for type safety."""
        _require(
            condition=isinstance(self.question, str),
            message="must be str",
            field_name="question",
            exc=TypeError,
        )
        _require(
            condition=isinstance(self.answer, str),
            message="must be str",
            field_name="answer",
            exc=TypeError,
        )
        # Prevent degenerate turns
        _require(
            condition=not (self.question.strip() == "" and self.answer.strip() == ""),
            message="cannot both be empty (after stripping whitespace)",
            field_name="question and answer",
        )
