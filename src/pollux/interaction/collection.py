"""``OutputCollection``: the aggregate result for source-pattern runs.

Fan-out, fan-in, and broadcast produce many interaction outputs. A collection
preserves per-interaction outputs and prompt/source indexes, exposes ergonomic
list accessors, and carries the partial-completion ``status`` that single
``Output`` deliberately does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pollux.interaction.output import Usage

if TYPE_CHECKING:
    from pollux.interaction.output import Output

#: ``"ok"`` when every answer is non-empty, ``"error"`` when all are empty,
#: ``"partial"`` otherwise.
CollectionStatus = Literal["ok", "partial", "error"]


@dataclass(frozen=True, slots=True)
class OutputCollection:
    """Aggregate result for a multi-call source pattern."""

    outputs: tuple[Output, ...] = ()
    prompt_indexes: tuple[int, ...] | None = None
    source_indexes: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        """Coerce the outputs sequence to an immutable tuple."""
        object.__setattr__(self, "outputs", tuple(self.outputs))

    @property
    def answers(self) -> list[str]:
        """Per-interaction primary text, in input order."""
        return [output.text for output in self.outputs]

    @property
    def structured(self) -> list[Any]:
        """Per-interaction structured payloads, in input order."""
        return [output.structured for output in self.outputs]

    @property
    def usage(self) -> Usage:
        """Token usage summed across interactions."""
        input_tokens = sum(o.usage.input_tokens for o in self.outputs)
        output_tokens = sum(o.usage.output_tokens for o in self.outputs)
        total_tokens = sum(o.usage.total_tokens for o in self.outputs)
        reasoning = [
            o.usage.reasoning_tokens
            for o in self.outputs
            if o.usage.reasoning_tokens is not None
        ]
        cached = [
            o.usage.cached_tokens
            for o in self.outputs
            if o.usage.cached_tokens is not None
        ]
        return Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            reasoning_tokens=sum(reasoning) if reasoning else None,
            cached_tokens=sum(cached) if cached else None,
        )

    @property
    def status(self) -> CollectionStatus:
        """Partial-completion status based on answer presence."""
        if not self.outputs:
            return "ok"
        empty = sum(1 for output in self.outputs if not output.text.strip())
        if empty == len(self.outputs):
            return "error"
        if empty > 0:
            return "partial"
        return "ok"

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict with per-output detail and aggregates."""
        payload: dict[str, Any] = {
            "status": self.status,
            "outputs": [output.to_jsonable() for output in self.outputs],
            "usage": self.usage.to_jsonable(),
        }
        if self.prompt_indexes is not None:
            payload["prompt_indexes"] = list(self.prompt_indexes)
        if self.source_indexes is not None:
            payload["source_indexes"] = list(self.source_indexes)
        return payload
