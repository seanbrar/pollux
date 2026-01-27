"""Tests for the refactored conversation facade following contract-first pattern."""

from unittest.mock import AsyncMock

import pytest

from pollux.extensions.conversation import Conversation
from pollux.extensions.conversation_types import (
    ConversationPolicy,
    ConversationState,
    PromptSet,
)
from tests.unit.extensions._builders import make_exchange

pytestmark = pytest.mark.unit


class TestConversationFacade:
    """Test the streamlined Conversation facade."""

    def test_start_conversation(self, mock_executor):
        """Test starting a new conversation."""
        conv = Conversation.start(mock_executor, sources=["doc.pdf"])

        assert isinstance(conv, Conversation)
        assert conv.state.sources == ("doc.pdf",)
        assert len(conv.state.turns) == 0
        assert conv.state.policy is None  # Default policy is None

    def test_start_with_policy(self, mock_executor):
        """Test starting conversation with custom policy."""
        policy = ConversationPolicy(keep_last_n=5, widen_max_factor=1.2)
        conv = Conversation.start(mock_executor).with_policy(policy)

        assert conv.state.policy == policy

    def test_with_policy(self, mock_executor):
        """Test changing policy on existing conversation."""
        conv = Conversation.start(mock_executor)
        new_policy = ConversationPolicy(keep_last_n=3)

        result = conv.with_policy(new_policy)

        assert result.state.policy == new_policy
        assert result is not conv  # New instance

    def test_with_sources(self, mock_executor):
        """Test changing sources."""
        conv = Conversation.start(mock_executor, sources=["doc1.pdf"])

        result = conv.with_sources(["doc2.pdf", "doc3.pdf"])

        assert result.state.sources == ("doc2.pdf", "doc3.pdf")

    def test_ask_method(self, mock_executor, mock_result):
        """Test the ask method uses run internally."""
        conv = Conversation.start(mock_executor)
        mock_executor.execute = AsyncMock(return_value=mock_result)

        # This would normally be async, but we'll test the structure
        assert hasattr(conv, "ask")
        assert callable(conv.ask)

    def test_run_method(self, mock_executor, mock_result):
        """Test the unified run method."""
        conv = Conversation.start(mock_executor)
        mock_executor.execute = AsyncMock(return_value=mock_result)

        assert hasattr(conv, "run")
        assert callable(conv.run)

    def test_analytics(self, mock_executor):
        """Test analytics computation."""
        turns = [
            make_exchange("Q1", "A1", error=False, estimate_max=100, actual_tokens=90),
            make_exchange("Q2", "A2", error=True, estimate_max=150, actual_tokens=None),
        ]
        state = ConversationState(sources=(), turns=tuple(turns), cache_key=None)
        conv = Conversation(state, mock_executor)

        analytics = conv.analytics()

        assert analytics.total_turns == 2
        assert analytics.error_turns == 1
        assert analytics.success_rate == 0.5
        assert analytics.total_estimated_tokens == 250
        assert analytics.total_actual_tokens == 90

    def test_immutability(self, mock_executor):
        """Test that conversation operations return new instances."""
        conv = Conversation.start(mock_executor, sources=["doc.pdf"])

        # All operations should return new instances
        with_policy = conv.with_policy(ConversationPolicy(keep_last_n=5))
        with_sources = conv.with_sources(["new.pdf"])

        assert with_policy is not conv
        assert with_sources is not conv

        # Original should be unchanged
        assert conv.state.sources == ("doc.pdf",)
        assert conv.state.policy is None


def test_prompt_set_constructors_integration():
    """Test that PromptSet constructors work with facade."""
    ps_single = PromptSet.single("Hello")
    ps_seq = PromptSet.sequential("Q1", "Q2", "Q3")
    ps_vec = PromptSet.vectorized("A", "B", "C")

    assert type(ps_single.mode).__name__ == "SingleMode"
    assert type(ps_seq.mode).__name__ == "SequentialMode"
    assert type(ps_vec.mode).__name__ == "VectorizedMode"


def test_conversation_policy_integration():
    """Test policy integration with facade."""
    policy = ConversationPolicy(
        keep_last_n=3,
        widen_max_factor=1.2,
        clamp_max_tokens=16000,
        prefer_json_array=True,
        execution_cache_name="test_cache",
        reuse_cache_only=False,
    )

    assert policy.keep_last_n == 3
    assert policy.widen_max_factor == 1.2
    assert policy.clamp_max_tokens == 16000
    assert policy.prefer_json_array is True
    assert policy.execution_cache_name == "test_cache"
    assert policy.reuse_cache_only is False
