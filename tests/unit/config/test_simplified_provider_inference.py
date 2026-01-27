"""Tests for the provider inference system.

Tests the streamlined resolve_provider function and pattern-based approach.
"""

import pytest

from pollux.config.utils import resolve_provider


class TestProviderInference:
    """Test the provider inference."""

    @pytest.mark.unit
    def test_exact_model_names(self):
        """Test exact model name matching."""
        assert resolve_provider("gemini-1.5-flash") == "google"
        assert resolve_provider("gemini-1.5-pro") == "google"
        assert resolve_provider("gpt-4o") == "openai"
        assert resolve_provider("claude-3-5-sonnet") == "anthropic"

    @pytest.mark.unit
    def test_version_patterns(self):
        """Test version-aware pattern matching."""
        assert resolve_provider("gemini-2.0-ultra") == "google"
        assert resolve_provider("gpt-5") == "openai"
        assert resolve_provider("claude-4-opus") == "anthropic"

    @pytest.mark.unit
    def test_prefix_fallbacks(self):
        """Test prefix-based fallback matching."""
        assert resolve_provider("gemini-unknown") == "google"
        assert resolve_provider("gpt-unknown") == "openai"
        assert resolve_provider("claude-unknown") == "anthropic"

    @pytest.mark.unit
    def test_default_behavior(self):
        """Test default behavior for unknown models."""
        assert resolve_provider("") == "google"
        assert resolve_provider("unknown-model") == "google"
        assert resolve_provider("random-model-name") == "google"

    @pytest.mark.unit
    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        assert resolve_provider("GEMINI-1.5-FLASH") == "google"
        assert resolve_provider("GPT-4O") == "openai"
        assert resolve_provider("Claude-3-5-Sonnet") == "anthropic"

    @pytest.mark.unit
    def test_priority_order(self):
        """Test that exact patterns take priority over prefixes."""
        # This would match both exact and prefix patterns, exact should win
        assert resolve_provider("gemini-1.5-flash") == "google"
        assert resolve_provider("gpt-4o") == "openai"
