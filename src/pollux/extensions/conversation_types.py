"""Typed, immutable data structures for the conversation extension."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .conversation_modes import ExecutionMode


@dataclass(frozen=True)
class Exchange:
    """A user/assistant turn with optional audit fields."""

    user: str
    assistant: str
    error: bool
    # optional audit fields surfaced by core Result/metrics (do not compute here)
    estimate_min: int | None = None
    estimate_max: int | None = None
    actual_tokens: int | None = None
    in_range: bool | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConversationPolicy:
    """Policy influencing planning hints and history windowing."""

    keep_last_n: int | None = None
    widen_max_factor: float | None = None
    clamp_max_tokens: int | None = None
    prefer_json_array: bool = False
    execution_cache_name: str | None = None
    reuse_cache_only: bool = False  # intent; provider capability decides behavior


@dataclass(frozen=True)
class PromptSet:
    """Prompts with execution mode for conversation processing.

    The mode determines both pipeline execution strategy and result formatting.
    Uses semantic types approach where mode behavior is explicit and isolated.
    """

    prompts: tuple[str, ...]
    mode: ExecutionMode = field(default_factory=lambda: _default_single_mode())

    @classmethod
    def single(cls, prompt: str) -> PromptSet:
        """Create a single prompt set."""
        from .conversation_modes import SingleMode

        return cls((prompt,), SingleMode())

    @classmethod
    def sequential(cls, *prompts: str) -> PromptSet:
        """Create sequential prompts as separate conversation turns."""
        from .conversation_modes import SequentialMode

        return cls(prompts, SequentialMode())

    @classmethod
    def vectorized(cls, *prompts: str) -> PromptSet:
        """Create vectorized batch execution with combined response."""
        from .conversation_modes import VectorizedMode

        return cls(prompts, VectorizedMode())


def _default_single_mode() -> ExecutionMode:
    """Provide default single mode to avoid circular imports."""
    from .conversation_modes import SingleMode

    return SingleMode()


@dataclass(frozen=True)
class ConversationState:
    """Immutable snapshot of sources, turns, cache, policy, and version."""

    sources: tuple[Any, ...]
    turns: tuple[Exchange, ...]
    cache_key: str | None = None
    cache_artifacts: tuple[str, ...] = ()
    cache_ttl_seconds: int | None = None
    policy: ConversationPolicy | None = None
    version: int = 0


@dataclass(frozen=True)
class BatchMetrics:
    """Normalized per-prompt and total metrics for a batch run."""

    per_prompt: tuple[dict[str, int | float], ...]
    totals: dict[str, int | float]


@dataclass(frozen=True)
class ConversationAnalytics:
    """Lightweight analytics summary across recorded exchanges."""

    total_turns: int
    error_turns: int
    success_rate: float
    total_estimated_tokens: int | None = None
    total_actual_tokens: int | None = None
    estimation_accuracy: float | None = None
    avg_response_length: float = 0.0
    total_user_chars: int = 0
    total_assistant_chars: int = 0
