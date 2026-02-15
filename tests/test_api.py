"""Real API integration tests.

These tests make actual API calls to Gemini and OpenAI. They are gated by:
- ENABLE_API_TESTS=1 (required to run any API tests)
- GEMINI_API_KEY (required for Gemini tests, from env or .env)
- OPENAI_API_KEY (required for OpenAI tests, from env or .env)

Tests use the cheapest models and minimal tokens to keep costs negligible.
Model selection is centralized in conftest.py for easy updates.
"""

from __future__ import annotations

import pytest

import pollux
from pollux.config import Config
from pollux.source import Source

pytestmark = [pytest.mark.api, pytest.mark.slow]


# =============================================================================
# Gemini Provider
# =============================================================================


@pytest.mark.asyncio
async def test_gemini_simple_text_roundtrip(
    gemini_api_key: str, gemini_test_model: str
) -> None:
    """Smoke: Gemini returns a coherent response for simple text."""
    config = Config(
        provider="gemini",
        model=gemini_test_model,
        api_key=gemini_api_key,
    )

    result = await pollux.run(
        "What is 2 + 2? Reply with just the number.",
        config=config,
    )

    assert result["status"] == "ok"
    assert len(result["answers"]) == 1
    assert "4" in result["answers"][0]


@pytest.mark.asyncio
async def test_gemini_with_text_source(
    gemini_api_key: str, gemini_test_model: str
) -> None:
    """Smoke: Gemini processes text source context correctly."""
    config = Config(
        provider="gemini",
        model=gemini_test_model,
        api_key=gemini_api_key,
    )

    result = await pollux.run(
        "What color is mentioned in the text?",
        source=Source.from_text("The sky is blue today."),
        config=config,
    )

    assert result["status"] == "ok"
    assert "blue" in result["answers"][0].lower()


@pytest.mark.asyncio
async def test_gemini_run_many_returns_multiple_answers(
    gemini_api_key: str, gemini_test_model: str
) -> None:
    """Smoke: Gemini run_many produces one answer per prompt."""
    config = Config(
        provider="gemini",
        model=gemini_test_model,
        api_key=gemini_api_key,
    )

    result = await pollux.run_many(
        prompts=["What is 1+1?", "What is 2+2?"],
        config=config,
    )

    assert result["status"] == "ok"
    assert len(result["answers"]) == 2
    assert result["metrics"]["n_calls"] == 2


# =============================================================================
# OpenAI Provider
# =============================================================================


@pytest.mark.asyncio
async def test_openai_simple_text_roundtrip(
    openai_api_key: str, openai_test_model: str
) -> None:
    """Smoke: OpenAI returns a coherent response for simple text."""
    config = Config(
        provider="openai",
        model=openai_test_model,
        api_key=openai_api_key,
    )

    result = await pollux.run(
        "What is 2 + 2? Reply with just the number.",
        config=config,
    )

    assert result["status"] == "ok"
    assert len(result["answers"]) == 1
    assert "4" in result["answers"][0]


@pytest.mark.asyncio
async def test_openai_with_text_source(
    openai_api_key: str, openai_test_model: str
) -> None:
    """Smoke: OpenAI processes text source context correctly."""
    config = Config(
        provider="openai",
        model=openai_test_model,
        api_key=openai_api_key,
    )

    result = await pollux.run(
        "What color is mentioned in the text?",
        source=Source.from_text("The sky is blue today."),
        config=config,
    )

    assert result["status"] == "ok"
    assert "blue" in result["answers"][0].lower()


@pytest.mark.asyncio
async def test_openai_run_many_returns_multiple_answers(
    openai_api_key: str, openai_test_model: str
) -> None:
    """Smoke: OpenAI run_many produces one answer per prompt."""
    config = Config(
        provider="openai",
        model=openai_test_model,
        api_key=openai_api_key,
    )

    result = await pollux.run_many(
        prompts=["What is 1+1?", "What is 2+2?"],
        config=config,
    )

    assert result["status"] == "ok"
    assert len(result["answers"]) == 2
    assert result["metrics"]["n_calls"] == 2
