"""Typed command states that flow through the pipeline.

These dataclasses define the shape of our data as it is transformed by
each stage of the pipeline.
"""

from __future__ import annotations

import dataclasses
import typing

from ._validation import _is_tuple_of, _require
from .execution_options import ExecutionOptions
from .turn import Turn

# Forward reference to avoid circular import with config module
if typing.TYPE_CHECKING:
    from pollux.config import FrozenConfig

    from .api_plan import ExecutionPlan
    from .sources import Source
    from .tokens import TokenEstimate


@dataclasses.dataclass(frozen=True, slots=True)
class InitialCommand:
    """The initial state of a request, created by the user."""

    sources: tuple[Source, ...]  # Forward reference to Source
    prompts: tuple[str, ...]
    config: FrozenConfig  # Forward reference
    history: tuple[Turn, ...] = dataclasses.field(default_factory=tuple)
    # Structured options conveying advanced execution behavior.
    options: ExecutionOptions | None = None

    def __post_init__(self) -> None:
        """Validate InitialCommand invariants."""
        _require(
            condition=isinstance(self.sources, tuple),
            message="must be a tuple",
            field_name="sources",
            exc=TypeError,
        )
        _require(
            condition=_is_tuple_of(self.prompts, str),
            message="must be a tuple[str, ...]",
            field_name="prompts",
            exc=TypeError,
        )
        # Ensure prompts structure is valid - content validation handled by prompt assembler
        _require(
            condition=self.prompts is not None,
            message="prompts field cannot be None",
            field_name="prompts",
        )
        # Prompts validation is handled by the prompt assembler, which has access to
        # configuration and can provide more specific error messages

        _require(
            condition=_is_tuple_of(self.history, Turn),
            message="must be a tuple[Turn, ...]",
            field_name="history",
            exc=TypeError,
        )
        _require(
            condition=self.options is None
            or isinstance(self.options, ExecutionOptions),
            message="must be an ExecutionOptions or None",
            field_name="options",
            exc=TypeError,
        )

    # Strict construction helper for friendlier early failures
    @classmethod
    def strict(
        cls,
        *,
        sources: tuple[Source, ...],
        prompts: tuple[str, ...],
        config: FrozenConfig,
        history: tuple[Turn, ...] = (),
        options: ExecutionOptions | None = None,
    ) -> InitialCommand:
        """Construct an `InitialCommand` ensuring at least one non-empty prompt.

        This surfaces prompt validity issues at creation time rather than during
        prompt assembly, improving onboarding and error locality.
        """
        _require(
            condition=isinstance(prompts, tuple)
            and all(isinstance(p, str) for p in prompts),
            message="prompts must be a tuple[str, ...]",
            field_name="prompts",
            exc=TypeError,
        )
        _require(
            condition=any((p or "").strip() for p in prompts),
            message="must contain at least one non-empty prompt",
            field_name="prompts",
        )
        return cls(
            sources=sources,
            prompts=prompts,
            config=config,
            history=history,
            options=options,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class ResolvedCommand:
    """The state after sources have been resolved."""

    initial: InitialCommand
    resolved_sources: tuple[Source, ...]  # Forward reference to Source


@dataclasses.dataclass(frozen=True, slots=True)
class PlannedCommand:
    """The state after an execution plan has been created."""

    resolved: ResolvedCommand
    execution_plan: ExecutionPlan
    token_estimate: TokenEstimate | None = None
    # Per-call estimates for vectorized plans
    per_call_estimates: tuple[TokenEstimate, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class FinalizedCommand:
    """The state after API calls have been executed."""

    planned: PlannedCommand
    raw_api_response: typing.Any
    # This will be populated by a future Telemetry handler/context.
    # Note: This field is intentionally mutable to collect metrics and is not
    # part of the immutability guarantees of the surrounding dataclass.
    telemetry_data: dict[str, object] = dataclasses.field(default_factory=dict)
