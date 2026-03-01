"""Shared pytest fixtures and test doubles."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
import logging
import os
from typing import Any

import pytest

from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import ProviderFileAsset, ProviderRequest, ProviderResponse

GEMINI_MODEL = "gemini-2.0-flash"
OPENAI_MODEL = "gpt-5-nano"
ANTHROPIC_MODEL = "claude-haiku-4-5"
CACHE_MODEL = "cache-model"
GEMINI_API_TEST_MODEL = "gemini-2.5-flash-lite-preview-09-2025"
OPENAI_API_TEST_MODEL = OPENAI_MODEL
ANTHROPIC_API_TEST_MODEL = ANTHROPIC_MODEL


@dataclass
class FakeProvider:
    """Provider double that captures calls for pipeline assertions."""

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

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.last_parts = request.parts
        self.last_generate_kwargs = {
            "system_instruction": request.system_instruction,
            "response_schema": request.response_schema,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "tools": request.tools,
            "tool_choice": request.tool_choice,
            "reasoning_effort": request.reasoning_effort,
            "history": request.history,
            "previous_response_id": request.previous_response_id,
            "provider_state": request.provider_state,
        }
        prompt = (
            request.parts[-1]
            if request.parts and isinstance(request.parts[-1], str)
            else ""
        )
        return ProviderResponse(text=f"ok:{prompt}", usage={"total_tokens": 1})

    async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:
        self.upload_calls += 1
        return ProviderFileAsset(
            file_id=f"mock://uploaded/{path.name}", provider="mock", mime_type=mime_type
        )

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
        if key.startswith(("GEMINI_", "OPENAI_", "ANTHROPIC_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("POLLUX_DEBUG_CONFIG", raising=False)


@pytest.fixture(scope="session", autouse=True)
def quiet_noisy_libraries():
    """Suppress noisy third-party loggers."""
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


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


@pytest.fixture
def gemini_model() -> str:
    """Return the canonical Gemini model for non-API tests."""
    return GEMINI_MODEL


@pytest.fixture
def openai_model() -> str:
    """Return the canonical OpenAI model for non-API tests."""
    return OPENAI_MODEL


@pytest.fixture
def cache_model() -> str:
    """Return the canonical cache test model name."""
    return CACHE_MODEL


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
    return GEMINI_API_TEST_MODEL


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
    return OPENAI_API_TEST_MODEL


@pytest.fixture
def anthropic_model() -> str:
    """Return the canonical Anthropic model for non-API tests."""
    return ANTHROPIC_MODEL


@pytest.fixture
def anthropic_api_key():
    """Return ANTHROPIC_API_KEY or skip the test if unavailable."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return key


@pytest.fixture
def anthropic_test_model():
    """Return the model to use for Anthropic API tests."""
    return ANTHROPIC_API_TEST_MODEL
