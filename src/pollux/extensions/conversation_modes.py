"""Execution modes for conversation extension.

This module implements the semantic types approach for handling different
conversation execution modes. Each mode is a protocol implementation that
defines both pipeline strategy mapping and result formatting behavior.

Architecture principles:
- Mode as data with behavior (not control flow)
- Pure protocol with immutable implementations
- Explicit mapping between execution strategy and presentation
- Zero magic, fully transparent behavior
- Structurally impossible to add incomplete modes

Example:
    from pollux.extensions.conversation_modes import SingleMode, SequentialMode, VectorizedMode
    from pollux.extensions.conversation_types import PromptSet

    # Using concrete modes
    single = PromptSet(("Hello",), SingleMode())
    sequential = PromptSet(("Q1", "Q2"), SequentialMode())
    vectorized = PromptSet(("Q1", "Q2", "Q3"), VectorizedMode())

    # Using convenience constructors
    single = PromptSet.single("Hello")
    sequential = PromptSet.sequential("Q1", "Q2")
    vectorized = PromptSet.vectorized("Q1", "Q2", "Q3")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .conversation_types import Exchange


@runtime_checkable
class ExecutionMode(Protocol):
    """Protocol defining how conversation modes map to execution and presentation.

    Each mode implementation must provide:
    1. Pipeline strategy mapping (how to execute)
    2. Exchange formatting (how to present results)

    This ensures modes are complete and self-contained.
    """

    def to_pipeline_strategy(self) -> Literal["sequential", "vectorized"]:
        """Map conversation mode to core pipeline execution strategy.

        Returns:
            "sequential" for turn-by-turn execution
            "vectorized" for batch execution with shared context
        """
        ...

    def format_exchanges(
        self,
        prompts: tuple[str, ...],
        answers: tuple[str, ...],
        metadata: dict[str, Any],
    ) -> tuple[Exchange, ...]:
        """Transform execution results into conversation exchanges.

        Args:
            prompts: User prompts that were executed
            answers: Assistant responses from execution
            metadata: Execution metadata (tokens, warnings, etc.)

        Returns:
            Tuple of Exchange objects representing conversation turns
        """
        ...


@dataclass(frozen=True)
class SingleMode:
    """Single prompt, single response mode.

    Maps to sequential pipeline strategy and creates one exchange.
    Used for simple ask() operations.
    """

    def to_pipeline_strategy(self) -> Literal["sequential", "vectorized"]:
        """Return the core pipeline strategy for this mode."""
        return "sequential"  # Single prompts use sequential pipeline

    def format_exchanges(
        self,
        prompts: tuple[str, ...],
        answers: tuple[str, ...],
        metadata: dict[str, Any],
    ) -> tuple[Exchange, ...]:
        """Format a single user/assistant exchange with normalization."""
        from .conversation_types import Exchange

        # Non-throwing normalization: use first prompt/answer when present,
        # and attach warnings if inputs were missing or had extras.
        norm_warnings: list[str] = []
        user = prompts[0] if prompts else ""
        assistant = str(answers[0]) if answers else ""
        if len(prompts) > 1:
            norm_warnings.append(
                f"SingleMode received {len(prompts)} prompts; using the first"
            )
        if len(answers) > 1:
            norm_warnings.append(
                f"SingleMode received {len(answers)} answers; using the first"
            )
        if not prompts:
            norm_warnings.append(
                "SingleMode received no prompts; recorded empty user text"
            )
        if not answers:
            norm_warnings.append(
                "SingleMode received no answers; recorded empty assistant text"
            )

        all_warnings = (*metadata.get("warnings", ()), *norm_warnings)

        return (
            Exchange(
                user=user,
                assistant=assistant,
                error=metadata.get("error", False),
                estimate_min=metadata.get("estimate_min"),
                estimate_max=metadata.get("estimate_max"),
                actual_tokens=metadata.get("actual_tokens"),
                in_range=metadata.get("in_range"),
                warnings=all_warnings,
            ),
        )


@dataclass(frozen=True)
class SequentialMode:
    """Sequential prompts as separate conversation turns.

    Maps to sequential pipeline strategy and creates one exchange per prompt.
    Each prompt becomes a distinct conversation turn with full context.
    """

    def to_pipeline_strategy(self) -> Literal["sequential", "vectorized"]:
        """Return the core pipeline strategy for this mode."""
        return "sequential"

    def format_exchanges(
        self,
        prompts: tuple[str, ...],
        answers: tuple[str, ...],
        metadata: dict[str, Any],
    ) -> tuple[Exchange, ...]:
        """Format one exchange per prompt with tolerant normalization."""
        from .conversation_types import Exchange

        # Non-throwing normalization: zip shortest; if prompts exceed answers,
        # fill missing answers with empty string and attach warnings; if answers
        # exceed prompts, drop extras with warnings.
        norm_warnings: list[str] = []
        n_p, n_a = len(prompts), len(answers)
        pairs: list[tuple[str, str]] = []
        for i in range(max(n_p, n_a)):
            p = prompts[i] if i < n_p else None
            a = str(answers[i]) if i < n_a else None
            if p is None and a is not None:
                # Extra answers without prompts are dropped
                if i == n_p:
                    norm_warnings.append(
                        f"SequentialMode received {n_a - n_p} extra answers; dropping extras"
                    )
                break
            if p is not None and a is None:
                # Provide empty assistant text for missing answers
                if i == n_a:
                    norm_warnings.append(
                        f"SequentialMode missing {n_p - n_a} answers; recording empty assistant text"
                    )
                pairs.append((p, ""))
            elif p is not None and a is not None:
                pairs.append((p, a))

        base_warnings = (*metadata.get("warnings", ()), *norm_warnings)

        return tuple(
            Exchange(
                user=prompt,
                assistant=str(answer),
                error=metadata.get("error", False),
                estimate_min=metadata.get("estimate_min"),
                estimate_max=metadata.get("estimate_max"),
                actual_tokens=metadata.get("actual_tokens"),
                in_range=metadata.get("in_range"),
                warnings=_distribute_warnings(base_warnings, i, len(pairs)),
            )
            for i, (prompt, answer) in enumerate(pairs)
        )


@dataclass(frozen=True)
class VectorizedMode:
    """Vectorized batch execution with combined response.

    Maps to vectorized pipeline strategy and creates one synthetic exchange
    representing the batch operation with combined results.
    """

    def to_pipeline_strategy(self) -> Literal["sequential", "vectorized"]:
        """Return the core pipeline strategy for this mode."""
        return "vectorized"

    def format_exchanges(
        self,
        prompts: tuple[str, ...],
        answers: tuple[str, ...],
        metadata: dict[str, Any],
    ) -> tuple[Exchange, ...]:
        """Format a single synthetic batch exchange with normalization."""
        from .conversation_types import Exchange

        # Non-throwing normalization: allow empty answers; join what exists and
        # attach warnings if inputs are empty.
        norm_warnings: list[str] = []
        if not prompts:
            norm_warnings.append(
                "VectorizedMode received no prompts; recorded empty batch label"
            )
        if not answers:
            norm_warnings.append(
                "VectorizedMode received no answers; recorded empty assistant text"
            )

        combined_prompt = (
            f"[vectorized x{len(prompts)}]" if prompts else "[vectorized x0]"
        )
        combined_answer = "; ".join(str(a) for a in answers) if answers else ""

        all_warnings = (*metadata.get("warnings", ()), *norm_warnings)

        return (
            Exchange(
                user=combined_prompt,
                assistant=combined_answer,
                error=metadata.get("error", False),
                estimate_min=metadata.get("estimate_min"),
                estimate_max=metadata.get("estimate_max"),
                actual_tokens=metadata.get("actual_tokens"),
                in_range=metadata.get("in_range"),
                warnings=all_warnings,
            ),
        )


def _distribute_warnings(
    warnings: tuple[str, ...], index: int, _total: int
) -> tuple[str, ...]:
    """Distribute warnings appropriately across sequential exchanges.

    Args:
        warnings: Original warnings tuple
        index: Current exchange index (0-based)
        total: Total number of exchanges

    Returns:
        Warnings tuple for this specific exchange.

    Note:
        Only the first exchange gets warnings to avoid duplication
        while maintaining traceability to the batch operation.
    """
    return warnings if index == 0 else ()
