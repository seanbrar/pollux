"""Lightweight builders for conversation extension tests.

These helpers keep tests focused on behavior by providing minimal,
typed construction of core extension data structures.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pollux.extensions.conversation_types import (
    ConversationPolicy,
    ConversationState,
    Exchange,
    PromptSet,
)


def make_state(
    *,
    sources: tuple[Any, ...] | None = None,
    turns: tuple[Any, ...] | None = None,
    cache_key: str | None = None,
    artifacts: tuple[str, ...] | None = None,
    ttl_seconds: int | None = None,
    policy: ConversationPolicy | None = None,
    version: int = 0,
) -> ConversationState:
    """Construct a `ConversationState` with sensible defaults."""
    return ConversationState(
        sources=tuple(sources or ()),
        turns=tuple(turns or ()),
        cache_key=cache_key,
        cache_artifacts=tuple(artifacts or ()),
        cache_ttl_seconds=ttl_seconds,
        policy=policy,
        version=version,
    )


def make_policy(**overrides: Any) -> ConversationPolicy:
    """Construct a `ConversationPolicy` applying any field overrides.

    Uses `dataclasses.replace` for clarity and future safety.
    """
    return replace(ConversationPolicy(), **overrides)


def make_prompt_set(mode: str, *prompts: str) -> PromptSet:
    """Create a `PromptSet` for a given mode name.

    Args:
        mode: One of "single", "sequential", or "vectorized".
        prompts: Prompt strings.
    """
    mode = mode.lower().strip()
    if mode == "single":
        if not prompts:
            raise ValueError("single mode requires exactly one prompt")
        return PromptSet.single(prompts[0])
    if mode == "sequential":
        return PromptSet.sequential(*prompts)
    if mode == "vectorized":
        return PromptSet.vectorized(*prompts)
    raise ValueError(f"Unknown mode: {mode}")


def make_exchange(
    user: str,
    assistant: str,
    *,
    error: bool = False,
    estimate_min: int | None = None,
    estimate_max: int | None = None,
    actual_tokens: int | None = None,
    in_range: bool | None = None,
    warnings: tuple[str, ...] | list[str] | None = None,
) -> Exchange:
    """Construct an `Exchange` with optional audit fields.

    Args:
        user: User question/content.
        assistant: Assistant response.
        error: Whether this turn represents an error.
        estimate_min/estimate_max/actual_tokens/in_range: Optional analytics fields.
        warnings: Optional warnings to attach.
    """
    return Exchange(
        user=user,
        assistant=assistant,
        error=error,
        estimate_min=estimate_min,
        estimate_max=estimate_max,
        actual_tokens=actual_tokens,
        in_range=in_range,
        warnings=tuple(warnings or ()),
    )
