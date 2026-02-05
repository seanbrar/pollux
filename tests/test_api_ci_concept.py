"""CI sanity checks for API key injection.

These tests verify that secrets are correctly injected before running
real API tests. They don't make network calls—just validate env setup.
"""

from __future__ import annotations

import pytest

from pollux.config import Config

pytestmark = pytest.mark.api


def test_gemini_api_key_is_available(gemini_api_key: str) -> None:
    """Verify GEMINI_API_KEY is correctly injected in CI."""
    assert len(gemini_api_key) > 0


def test_gemini_config_resolves_api_key(
    gemini_api_key: str, gemini_test_model: str
) -> None:
    """Verify Config correctly resolves the Gemini API key from env."""
    config = Config(provider="gemini", model=gemini_test_model)
    assert config.api_key == gemini_api_key


def test_openai_api_key_is_available(openai_api_key: str) -> None:
    """Verify OPENAI_API_KEY is correctly injected in CI."""
    assert len(openai_api_key) > 0


def test_openai_config_resolves_api_key(
    openai_api_key: str, openai_test_model: str
) -> None:
    """Verify Config correctly resolves the OpenAI API key from env."""
    config = Config(provider="openai", model=openai_test_model)
    assert config.api_key == openai_api_key
