import pytest

from pollux.config import resolve_provider

pytestmark = pytest.mark.unit


class TestProviderInference:
    """Test the data-driven provider inference logic."""

    @pytest.mark.smoke
    def test_provider_inference_gemini_models(self):
        """Should identify Google as provider for gemini- prefixed models."""
        assert resolve_provider("gemini-1.5-flash") == "google"
        assert resolve_provider("gemini-2.0-pro") == "google"
        assert resolve_provider("GEMINI-1.5-FLASH") == "google"  # Case insensitive

    def test_provider_inference_openai_models(self):
        """Should identify OpenAI as provider for gpt- prefixed models."""
        assert resolve_provider("gpt-4") == "openai"
        assert resolve_provider("gpt-3.5-turbo") == "openai"
        assert resolve_provider("GPT-4") == "openai"  # Case insensitive

    def test_provider_inference_anthropic_models(self):
        """Should identify Anthropic as provider for claude- prefixed models."""
        assert resolve_provider("claude-3-sonnet") == "anthropic"
        assert resolve_provider("claude-2") == "anthropic"
        assert resolve_provider("CLAUDE-3-OPUS") == "anthropic"  # Case insensitive

    def test_provider_inference_unknown_model_defaults_to_google(self):
        """Unknown models should default to Google provider."""
        assert resolve_provider("unknown-model") == "google"
        assert resolve_provider("custom-model-v1") == "google"
        assert resolve_provider("") == "google"
