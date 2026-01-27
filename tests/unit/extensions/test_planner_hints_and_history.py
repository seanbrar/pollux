from __future__ import annotations

import pytest

from pollux.extensions.conversation_modes import SingleMode, VectorizedMode
from pollux.extensions.conversation_planner import compile_conversation
from pollux.extensions.conversation_types import (
    ConversationPolicy,
    ConversationState,
    PromptSet,
)

pytestmark = pytest.mark.unit


def test_history_window_applied() -> None:
    # Prepare prior turns
    from pollux.extensions.conversation_types import Exchange

    turns = (
        Exchange("q1", "a1", error=False),
        Exchange("q2", "a2", error=False),
        Exchange("q3", "a3", error=False),
    )
    state = ConversationState(sources=("doc.pdf",), turns=turns)
    policy = ConversationPolicy(keep_last_n=2)
    plan = compile_conversation(state, PromptSet.single("New?"), policy)

    assert len(plan.history) == 2
    assert plan.history[0].question == "q2"
    assert plan.history[1].question == "q3"


def test_policy_creates_hints_tuple() -> None:
    state = ConversationState(sources=("doc.pdf",), turns=())
    policy = ConversationPolicy(
        widen_max_factor=1.2,
        clamp_max_tokens=16000,
        prefer_json_array=True,
        execution_cache_name="demo",
    )
    plan = compile_conversation(state, PromptSet(("Q",), SingleMode()), policy)

    # Hints present and inspectable (names depend on core types)
    assert isinstance(plan.hints, tuple)
    names = [type(h).__name__ for h in plan.hints]
    assert any("Estimation" in n for n in names)
    assert any("Result" in n for n in names)


def test_vectorized_maps_strategy() -> None:
    state = ConversationState(sources=("doc.pdf",), turns=())
    plan = compile_conversation(
        state, PromptSet(("Q1", "Q2"), VectorizedMode()), ConversationPolicy()
    )
    assert plan.strategy in ("vectorized", "sequential")
