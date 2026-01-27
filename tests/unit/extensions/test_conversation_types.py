"""Tests for conversation_types.py following contract-first pattern."""

import pytest

from pollux.core.turn import Turn
from pollux.extensions.conversation_modes import (
    SequentialMode,
    SingleMode,
    VectorizedMode,
)
from pollux.extensions.conversation_planner import ConversationPlan
from pollux.extensions.conversation_types import (
    BatchMetrics,
    ConversationAnalytics,
    ConversationPolicy,
    PromptSet,
)

pytestmark = pytest.mark.unit


def test_conversation_policy_immutability():
    """Test that ConversationPolicy is immutable."""
    policy = ConversationPolicy(keep_last_n=5, widen_max_factor=1.2)

    # Should be frozen dataclass - these should fail
    with pytest.raises(AttributeError):
        policy.keep_last_n = 10  # type: ignore

    with pytest.raises(AttributeError):
        policy.widen_max_factor = 1.5  # type: ignore


def test_conversation_policy_defaults():
    """Test default values for ConversationPolicy."""
    policy = ConversationPolicy()

    assert policy.keep_last_n is None
    assert policy.widen_max_factor is None
    assert policy.clamp_max_tokens is None
    assert policy.prefer_json_array is False
    assert policy.execution_cache_name is None
    assert policy.reuse_cache_only is False


def test_prompt_set_constructors():
    """Test PromptSet direct construction."""
    # Single prompt
    ps_single = PromptSet(("Hello",), SingleMode())
    assert ps_single.prompts == ("Hello",)
    assert ps_single.mode == SingleMode()

    # Sequential prompts
    ps_seq = PromptSet(("Q1", "Q2", "Q3"), SequentialMode())
    assert ps_seq.prompts == ("Q1", "Q2", "Q3")
    assert ps_seq.mode == SequentialMode()

    # Vectorized prompts
    ps_vec = PromptSet(("A", "B", "C"), VectorizedMode())
    assert ps_vec.prompts == ("A", "B", "C")
    assert ps_vec.mode == VectorizedMode()


def test_prompt_set_direct_construction():
    """Test direct PromptSet construction."""
    ps = PromptSet(("P1", "P2"), SequentialMode())
    assert ps.prompts == ("P1", "P2")
    assert ps.mode == SequentialMode()


def test_prompt_set_immutability():
    """Test that PromptSet is immutable."""
    ps = PromptSet(("Test",), SingleMode())

    with pytest.raises(AttributeError):
        ps.prompts = ("Modified",)  # type: ignore

    with pytest.raises(AttributeError):
        ps.mode = SingleMode()  # type: ignore


def test_conversation_plan_immutability():
    """Test that ConversationPlan is immutable."""
    plan = ConversationPlan(
        sources=("doc.pdf",),
        history=(),
        prompts=("Q1",),
        strategy="sequential",
        hints=(),
    )

    with pytest.raises(AttributeError):
        plan.prompts = ("Modified",)  # type: ignore

    with pytest.raises(AttributeError):
        plan.strategy = "vectorized"  # type: ignore


def test_conversation_plan_attributes():
    """Test ConversationPlan attributes."""
    plan = ConversationPlan(
        sources=("doc.pdf", "notes.txt"),
        history=(Turn("Q1", "A1"), Turn("Q2", "A2")),
        prompts=("What is this?", "Summarize"),
        strategy="vectorized",
        hints=(object(), object()),  # Mock hint objects
    )

    assert plan.sources == ("doc.pdf", "notes.txt")
    assert len(plan.history) == 2
    assert plan.prompts == ("What is this?", "Summarize")
    assert plan.strategy == "vectorized"
    assert len(plan.hints) == 2


def test_batch_metrics_immutability():
    """Test that BatchMetrics is immutable."""
    metrics = BatchMetrics(
        per_prompt=({"tokens": 100}, {"tokens": 150}),
        totals={"total_tokens": 250},
    )

    with pytest.raises(AttributeError):
        metrics.per_prompt = ()  # type: ignore

    with pytest.raises(AttributeError):
        metrics.totals = {}  # type: ignore


def test_conversation_analytics_immutability():
    """Test that ConversationAnalytics is immutable."""
    analytics = ConversationAnalytics(
        total_turns=5,
        error_turns=1,
        success_rate=0.8,
        total_estimated_tokens=1000,
        total_actual_tokens=950,
        estimation_accuracy=0.95,
        avg_response_length=150.0,
        total_user_chars=300,
        total_assistant_chars=600,
    )

    with pytest.raises(AttributeError):
        analytics.total_turns = 10  # type: ignore

    with pytest.raises(AttributeError):
        analytics.success_rate = 1.0  # type: ignore


def test_conversation_analytics_defaults():
    """Test default values for ConversationAnalytics."""
    analytics = ConversationAnalytics(total_turns=0, error_turns=0, success_rate=1.0)

    assert analytics.total_estimated_tokens is None
    assert analytics.total_actual_tokens is None
    assert analytics.estimation_accuracy is None
    assert analytics.avg_response_length == 0.0
    assert analytics.total_user_chars == 0
    assert analytics.total_assistant_chars == 0


def test_prompt_set_empty_prompts():
    """Test PromptSet with empty prompts."""
    ps = PromptSet((), SingleMode())
    assert ps.prompts == ()
    assert ps.mode == SingleMode()


def test_prompt_set_single_prompt_optimization():
    """Test that single prompt in any mode still works."""
    ps = PromptSet(("Single",), VectorizedMode())  # Even though vectorized
    assert ps.prompts == ("Single",)
    assert ps.mode == VectorizedMode()  # Mode is preserved


def test_prompt_set_tuple_immutability():
    """Test that the prompts tuple itself is immutable."""
    ps = PromptSet(("A", "B"), SequentialMode())

    # The tuple should be immutable
    with pytest.raises(AttributeError):
        ps.prompts.append("C")  # type: ignore

    with pytest.raises(TypeError):
        ps.prompts[0] = "Modified"  # type: ignore
