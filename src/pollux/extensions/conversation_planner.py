"""Compile conversation inputs into a pure `ConversationPlan`.

This module keeps planning pure and data-centric. Strategy selection delegates
to the execution mode on the `PromptSet`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pollux.core.execution_options import (
    CacheOptions,
    EstimationOptions,
    ExecutionOptions,
    ResultOption,
)
from pollux.core.types import Turn

if TYPE_CHECKING:
    from .conversation_types import ConversationPolicy, ConversationState, PromptSet


@dataclass(frozen=True)
class ConversationPlan:
    """Pure, inspectable plan for executing a conversation step."""

    sources: tuple[Any, ...]
    history: tuple[Turn, ...]
    prompts: tuple[str, ...]
    strategy: Literal["sequential", "vectorized"]
    # Back-compat, inspectable hints view for audits/demos/tests
    hints: tuple[Any, ...] = field(default_factory=tuple)
    options: ExecutionOptions | None = None


def compile_conversation(
    state: ConversationState, prompt_set: PromptSet, policy: ConversationPolicy | None
) -> ConversationPlan:
    """Compile state and inputs into a `ConversationPlan`.

    Args:
        state: Current conversation state snapshot.
        prompt_set: Prompts plus mode driving execution and formatting.
        policy: Optional policy controlling hints and history windowing.

    Returns:
        An immutable plan that can be inspected or executed.
    """
    # history window
    full = tuple(Turn(q.user, q.assistant, q.error) for q in state.turns)
    hist = (
        full[-policy.keep_last_n :]
        if (policy and policy.keep_last_n and policy.keep_last_n > 0)
        else full
    )

    # Build structured ExecutionOptions from state + policy
    cache_hint = None
    if state.cache_key:
        cache_hint = CacheOptions(
            deterministic_key=state.cache_key,
            artifacts=state.cache_artifacts,
            ttl_seconds=state.cache_ttl_seconds,
            reuse_only=bool(policy and policy.reuse_cache_only),
        )
    estimation = None
    if policy and (policy.widen_max_factor or policy.clamp_max_tokens):
        estimation = EstimationOptions(
            widen_max_factor=policy.widen_max_factor or 1.0,
            clamp_max_tokens=policy.clamp_max_tokens,
        )
    result = (
        ResultOption(prefer_json_array=True)
        if (policy and policy.prefer_json_array)
        else None
    )
    cache_override = (
        policy.execution_cache_name
        if (policy and policy.execution_cache_name)
        else None
    )

    options = None
    if any([cache_hint, estimation, result, cache_override]):
        options = ExecutionOptions(
            cache=cache_hint,
            estimation=estimation,
            result=result,
            cache_override_name=cache_override,
        )
    # Compose a lightweight hints view for inspectability (non-authoritative)
    hints: list[Any] = []
    if cache_hint is not None:
        hints.append(cache_hint)
    if estimation is not None:
        hints.append(estimation)
    if result is not None:
        hints.append(result)
    if cache_override is not None:
        hints.append({"cache_override_name": cache_override})

    # strategy delegation to mode (pure data transformation)
    strategy = prompt_set.mode.to_pipeline_strategy()
    return ConversationPlan(
        sources=state.sources,
        history=hist,
        prompts=prompt_set.prompts,
        strategy=strategy,
        options=options,
        hints=tuple(hints),
    )
