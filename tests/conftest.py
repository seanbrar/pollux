"""Pytest configuration and fixtures.

Provides environment isolation, logging configuration, marker registration,
and automatic API test skipping. All fixtures here are autouse unless noted.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
import logging
import os
from typing import Any

import pytest

from pollux.providers.base import ProviderCapabilities

# =============================================================================
# Test Doubles
# =============================================================================


@dataclass
class FakeProvider:
    """Provider test double for pipeline behavior verification.

    Captures method calls and returns configurable responses. Use to test
    pipeline behavior without making real API calls.
    """

    cache_calls: int = 0
    upload_calls: int = 0
    last_parts: list[Any] | None = None
    last_generate_kwargs: dict[str, Any] | None = None
    _capabilities: ProviderCapabilities = field(
        default_factory=lambda: ProviderCapabilities(
            caching=True,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=False,
        )
    )

    @property
    def supports_caching(self) -> bool:
        return self.capabilities.caching

    @property
    def supports_uploads(self) -> bool:
        return self.capabilities.uploads

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def generate(
        self,
        *,
        model: str,
        parts: list[Any],
        system_instruction: str | None = None,
        cache_name: str | None = None,
        response_schema: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        history: list[dict[str, str]] | None = None,
        delivery_mode: str = "realtime",
        previous_response_id: str | None = None,
    ) -> dict[str, Any]:
        del model, system_instruction, cache_name
        self.last_parts = parts
        self.last_generate_kwargs = {
            "response_schema": response_schema,
            "reasoning_effort": reasoning_effort,
            "history": history,
            "delivery_mode": delivery_mode,
            "previous_response_id": previous_response_id,
        }
        prompt = parts[-1] if parts and isinstance(parts[-1], str) else ""
        return {"text": f"ok:{prompt}", "usage": {"total_token_count": 1}}

    async def upload_file(self, path: Any, mime_type: str) -> str:
        del mime_type
        self.upload_calls += 1
        return f"mock://uploaded/{path.name}"

    async def create_cache(
        self,
        *,
        model: str,
        parts: list[Any],
        system_instruction: str | None = None,
        ttl_seconds: int = 3600,
    ) -> str:
        del model, parts, system_instruction, ttl_seconds
        self.cache_calls += 1
        return "cachedContents/test"


# =============================================================================
# Environment Isolation (Autouse)
# =============================================================================


@pytest.fixture(autouse=True)
def block_dotenv(request, monkeypatch):
    """Prevent python-dotenv from loading project .env files during tests.

    Opt-out: @pytest.mark.allow_dotenv
    """
    if request.node.get_closest_marker("allow_dotenv"):
        return
    with suppress(Exception):
        monkeypatch.setattr(
            "dotenv.load_dotenv", lambda *_args, **_kwargs: False, raising=False
        )


@pytest.fixture(autouse=True)
def isolate_provider_env(request, monkeypatch):
    """Ensure a clean provider environment for each test.

    Clears GEMINI_* and OPENAI_* env vars to prevent test pollution.
    Opt-out: @pytest.mark.allow_env_pollution or @pytest.mark.api
    """
    if request.node.get_closest_marker("allow_env_pollution") or (
        "api" in request.node.keywords
    ):
        return

    for key in list(os.environ.keys()):
        if key.startswith(("GEMINI_", "OPENAI_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("POLLUX_DEBUG_CONFIG", raising=False)


# =============================================================================
# Logging
# =============================================================================


@pytest.fixture(scope="session", autouse=True)
def quiet_noisy_libraries():
    """Suppress noisy third-party loggers."""
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


# =============================================================================
# Pytest Hooks
# =============================================================================

API_TESTS_REASON = "API tests require ENABLE_API_TESTS=1"


def _api_tests_enabled() -> bool:
    return bool(os.getenv("ENABLE_API_TESTS"))


def pytest_collection_modifyitems(items):
    """Automatically skip API tests when not explicitly enabled."""
    if _api_tests_enabled():
        return
    skip_api = pytest.mark.skip(reason=API_TESTS_REASON)
    for item in items:
        if "api" in item.keywords:
            item.add_marker(skip_api)


# =============================================================================
# API Test Configuration
# =============================================================================

# Models used for API tests. Chosen for cost efficiency:
# - Gemini: 2.5-flash-lite-preview is same price as 2.0-flash with better performance
# - OpenAI: gpt-5-nano is 3x cheaper input, 15x cheaper output than gpt-4o-mini
_GEMINI_TEST_MODEL = "gemini-2.5-flash-lite-preview-09-2025"
_OPENAI_TEST_MODEL = "gpt-5-nano"


@pytest.fixture
def gemini_api_key():
    """Return GEMINI_API_KEY or skip the test if unavailable."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    return key


@pytest.fixture
def gemini_test_model():
    """Return the model to use for Gemini API tests."""
    return _GEMINI_TEST_MODEL


@pytest.fixture
def openai_api_key():
    """Return OPENAI_API_KEY or skip the test if unavailable."""
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        pytest.skip("OPENAI_API_KEY not set")
    return key


@pytest.fixture
def openai_test_model():
    """Return the model to use for OpenAI API tests."""
    return _OPENAI_TEST_MODEL
