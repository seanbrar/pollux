"""Tests for conversation_planner.py following contract-first pattern."""

import pytest

from pollux.extensions.conversation_planner import (
    ConversationPlan,
    compile_conversation,
)
from pollux.extensions.conversation_types import (
    ConversationPolicy,
    Exchange,
    PromptSet,
)
from tests.unit.extensions._builders import make_prompt_set, make_state

pytestmark = pytest.mark.unit


def test_compile_conversation_basic():
    """Test basic conversation compilation."""
    state = make_state(sources=("doc.pdf",), turns=())
    policy = ConversationPolicy()
    prompt_set = make_prompt_set("single", "Hello world")

    plan = compile_conversation(state, prompt_set, policy)

    assert isinstance(plan, ConversationPlan)
    assert plan.sources == ("doc.pdf",)
    assert plan.prompts == ("Hello world",)
    assert plan.strategy == "sequential"
    assert len(plan.hints) == 0  # No hints for basic case


def test_compile_conversation_with_history_window():
    """Test that history window is properly applied."""
    # Build prior turns using the extension's Exchange type
    turns: tuple[Exchange, ...] = (
        Exchange("q1", "a1", error=False),
        Exchange("q2", "a2", error=False),
        Exchange("q3", "a3", error=False),
    )
    state = make_state(sources=("doc.pdf",), turns=turns)
    policy = ConversationPolicy(keep_last_n=2)
    prompt_set = PromptSet.single("New question")

    plan = compile_conversation(state, prompt_set, policy)

    assert len(plan.history) == 2
    assert plan.history[0].question == "q2"
    assert plan.history[1].question == "q3"


def test_compile_conversation_with_cache_key():
    """Test that cache key creates appropriate hints."""
    state = make_state(
        sources=("doc.pdf",),
        turns=(),
        cache_key="test_key",
        artifacts=("artifact1",),
    )
    policy = ConversationPolicy()
    prompt_set = make_prompt_set("single", "Question")

    plan = compile_conversation(state, prompt_set, policy)

    # Hints are now structured via ExecutionOptions; verify cache options present
    assert len(plan.hints) > 0
    hint_names = [type(h).__name__ for h in plan.hints]
    assert "CacheOptions" in hint_names
    # And options carry a CacheOptions with our deterministic key
    assert plan.options is not None
    assert plan.options.cache is not None
    assert plan.options.cache.deterministic_key == "test_key"


def test_compile_conversation_with_policy_hints():
    """Test that policy settings create appropriate hints."""
    state = make_state(sources=("doc.pdf",), turns=())
    policy = ConversationPolicy(
        widen_max_factor=1.2,
        clamp_max_tokens=16000,
        prefer_json_array=True,
        execution_cache_name="test_cache",
    )
    prompt_set = make_prompt_set("single", "Question")

    plan = compile_conversation(state, prompt_set, policy)

    # Structured options are exposed in plan.options and lightly mirrored in hints
    assert plan.options is not None
    assert plan.options.estimation is not None
    assert plan.options.estimation.widen_max_factor == 1.2
    assert plan.options.estimation.clamp_max_tokens == 16000
    assert plan.options.result is not None
    assert plan.options.result.prefer_json_array is True
    assert plan.options.cache_override_name == "test_cache"
    # Hints include typed capsules for inspectability
    hint_names = [type(h).__name__ for h in plan.hints]
    assert "EstimationOptions" in hint_names
    assert "ResultOption" in hint_names


def test_compile_conversation_vectorized_mode():
    """Test that vectorized mode is preserved in plan."""
    state = make_state(sources=("doc.pdf",), turns=())
    policy = ConversationPolicy()
    prompt_set = make_prompt_set("vectorized", "Q1", "Q2", "Q3")

    plan = compile_conversation(state, prompt_set, policy)

    assert plan.prompts == ("Q1", "Q2", "Q3")
    # Vectorized mode now maps to vectorized strategy
    assert plan.strategy == "vectorized"


def test_compile_conversation_sequential_mode():
    """Test that sequential mode is preserved in plan."""
    state = make_state(sources=("doc.pdf",), turns=())
    policy = ConversationPolicy()
    prompt_set = make_prompt_set("sequential", "Q1", "Q2", "Q3")

    plan = compile_conversation(state, prompt_set, policy)

    assert plan.prompts == ("Q1", "Q2", "Q3")
    assert plan.strategy == "sequential"


def test_compile_conversation_empty_prompts():
    """Test compilation with empty prompts."""
    state = make_state(sources=("doc.pdf",), turns=())
    policy = ConversationPolicy()
    prompt_set = make_prompt_set("sequential")

    plan = compile_conversation(state, prompt_set, policy)

    assert plan.prompts == ()
    assert plan.strategy == "sequential"


def test_compile_conversation_single_prompt_optimization():
    """Test that single prompt always uses sequential strategy."""
    state = make_state(sources=("doc.pdf",), turns=())
    policy = ConversationPolicy()
    prompt_set = make_prompt_set("single", "Single prompt")

    plan = compile_conversation(state, prompt_set, policy)

    assert plan.strategy == "sequential"


def test_compile_conversation_reuse_cache_only():
    """Test that reuse_cache_only policy affects cache hints."""
    state = make_state(
        sources=("doc.pdf",),
        turns=(),
        cache_key="test_key",
        artifacts=("artifact1",),
    )
    policy = ConversationPolicy(reuse_cache_only=True)
    prompt_set = make_prompt_set("single", "Question")

    plan = compile_conversation(state, prompt_set, policy)

    # Verify options reflect reuse-only cache policy
    assert plan.options is not None
    assert plan.options.cache is not None
    assert plan.options.cache.reuse_only is True
    # Hints should include CacheOptions capsule
    cache_hints = [h for h in plan.hints if type(h).__name__ == "CacheOptions"]
    assert len(cache_hints) == 1
    assert cache_hints[0].reuse_only is True
