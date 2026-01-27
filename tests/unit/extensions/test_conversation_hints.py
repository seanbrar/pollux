"""Unit tests for conversation extension cache hint integration."""

import pytest

from pollux.extensions.conversation import Conversation
from tests.unit.extensions._builders import make_state

pytestmark = pytest.mark.unit


class TestConversationCache:
    """Test conversation extension cache functionality."""

    # executor fixture provided by tests/unit/extensions/conftest.py

    @pytest.mark.asyncio
    async def test_conversation_with_cache_key(self, executor):
        """Test that conversation works with cache key in state."""
        # Create conversation state with cache key
        from pollux.core.types import Source

        state = make_state(
            sources=(Source.from_text("doc"),),
            turns=(),
            cache_key="test-cache-key",
            artifacts=("artifact1",),
        )
        conv = Conversation(state, executor)

        # Test that cache key is preserved
        assert conv.state.cache_key == "test-cache-key"
        assert conv.state.cache_artifacts == ("artifact1",)

        # Test that conversation can still function
        conv2 = await conv.ask("test question")
        assert len(conv2.state.turns) == 1

    @pytest.mark.asyncio
    async def test_conversation_without_cache_key(self, executor):
        """Test conversation works without cache key."""
        from pollux.core.types import Source

        conv = Conversation.start(executor, sources=(Source.from_text("doc"),))

        # Test that cache key is None by default
        assert conv.state.cache_key is None
        assert conv.state.cache_artifacts == ()

        # Test that conversation can still function
        conv2 = await conv.ask("test question")
        assert len(conv2.state.turns) == 1
