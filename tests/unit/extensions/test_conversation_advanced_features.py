"""Unit tests for advanced conversation extension features."""

import pytest

from pollux.extensions.conversation import Conversation
from pollux.extensions.conversation_types import (
    ConversationAnalytics,
    ConversationPolicy,
)
from tests.unit.extensions._builders import make_state

# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit


class TestBasicConversation:
    """Test basic conversation functionality."""

    # executor fixture provided by tests/unit/extensions/conftest.py

    @pytest.mark.asyncio
    async def test_basic_conversation_flow(self, executor):
        """Test basic conversation flow."""
        conv = Conversation.start(executor, sources=())

        # Test that conversation starts properly
        assert len(conv.state.turns) == 0
        assert conv.state.sources == ()

        # Test with_policy method exists
        conv_with_policy = conv.with_policy(ConversationPolicy(keep_last_n=5))
        assert conv_with_policy.state.policy is not None
        assert conv_with_policy.state.policy.keep_last_n == 5

        # Test with_sources method exists
        conv_with_sources = conv.with_sources("test.pdf")
        assert "test.pdf" in conv_with_sources.state.sources


class TestConversationAnalytics:
    """Test conversation analytics and observability."""

    # executor fixture provided by tests/unit/extensions/conftest.py

    def test_analytics_empty_conversation(self, executor):
        """Test analytics for empty conversation."""
        conv = Conversation.start(executor, sources=())
        analytics = conv.analytics()

        assert isinstance(analytics, ConversationAnalytics)
        assert analytics.total_turns == 0
        assert analytics.error_turns == 0
        assert analytics.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_analytics_with_conversation(self, executor):
        """Test analytics with actual conversation turns."""
        conv = Conversation.start(executor, sources=())
        conv = await conv.ask("Question 1")
        conv = await conv.ask("Question 2")

        analytics = conv.analytics()

        assert analytics.total_turns == 2
        assert analytics.error_turns == 0
        assert analytics.success_rate == 1.0
        assert analytics.avg_response_length > 0
        assert analytics.total_user_chars > 0
        assert analytics.total_assistant_chars > 0


class TestConversationState:
    """Test conversation state management."""

    # executor fixture not required in this class; using direct state constructs

    def test_conversation_state_immutability(self):
        """Test that ConversationState is immutable."""
        state = make_state(sources=("doc.pdf",), turns=())

        # Should not be able to modify state
        with pytest.raises(AttributeError):
            state.sources = ("modified.pdf",)  # type: ignore
