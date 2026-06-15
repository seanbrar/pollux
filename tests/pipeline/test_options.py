"""Pipeline boundary tests."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
import pytest

import pollux
import pollux.cache
from pollux.config import Config
from pollux.errors import (
    ConfigurationError,
)
from pollux.options import Options
from pollux.providers.anthropic import AnthropicProvider
from pollux.providers.base import (
    ProviderCapabilities,
)
from pollux.source import Source
from tests.conftest import (
    ANTHROPIC_MODEL,
    GEMINI_MODEL,
    FakeProvider,
)
from tests.helpers import CaptureProvider as KwargsCaptureProvider

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("option_kwargs", "match"),
    [
        ({"response_schema": {"type": "object"}}, "structured outputs"),
        ({"reasoning_effort": "high"}, "reasoning"),
        ({"reasoning_budget_tokens": 0}, "reasoning"),
    ],
    ids=["structured_outputs", "reasoning_effort", "reasoning_budget_tokens"],
)
async def test_option_requires_provider_capability(
    option_kwargs: dict[str, Any],
    match: str,
) -> None:
    """Strict capability checks reject unsupported options."""
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match=match):
        await pollux.run(
            "Q",
            config=cfg,
            options=Options(**option_kwargs),
        )


def test_options_system_instruction_requires_string() -> None:
    """Invalid system_instruction types should fail fast at option construction."""
    with pytest.raises(ConfigurationError, match="system_instruction must be a string"):
        Options(system_instruction=123)  # type: ignore[arg-type]


def test_options_reasoning_budget_tokens_requires_non_negative_int() -> None:
    """Budget-based reasoning control should validate shape at option creation."""
    with pytest.raises(
        ConfigurationError,
        match="reasoning_budget_tokens must be a non-negative integer",
    ):
        Options(reasoning_budget_tokens=-1)


def test_options_reasoning_budget_tokens_rejects_bool() -> None:
    """Boolean values should not be accepted as integer reasoning budgets."""
    with pytest.raises(
        ConfigurationError,
        match="reasoning_budget_tokens must be a non-negative integer",
    ):
        Options(reasoning_budget_tokens=True)


def test_options_reasoning_controls_are_mutually_exclusive() -> None:
    """Qualitative and quantitative reasoning controls should not mix."""
    with pytest.raises(
        ConfigurationError,
        match="reasoning_effort and reasoning_budget_tokens are mutually exclusive",
    ):
        Options(reasoning_effort="high", reasoning_budget_tokens=0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reasoning_options", "expected_effort", "expected_budget"),
    [
        ({"reasoning_effort": "high"}, "high", None),
        ({"reasoning_budget_tokens": 0}, None, 0),
    ],
    ids=["reasoning_effort", "reasoning_budget_tokens"],
)
async def test_options_are_forwarded_when_provider_supports_features(
    monkeypatch: pytest.MonkeyPatch,
    reasoning_options: dict[str, Any],
    expected_effort: str | None,
    expected_budget: int | None,
) -> None:
    """Options should be normalized and passed through to provider.generate()."""

    class ExampleSchema(BaseModel):
        name: str

    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=True,
            reasoning=True,
            reasoning_budget_tokens=True,
            deferred_delivery=True,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    await pollux.run_many(
        ("Q1?",),
        sources=(Source.from_text("context"),),
        config=cfg,
        options=Options(
            system_instruction="Reply in one sentence.",
            response_schema=ExampleSchema,
            **reasoning_options,
        ),
    )

    assert fake.last_generate_kwargs is not None
    assert fake.last_generate_kwargs["reasoning_effort"] == expected_effort
    assert fake.last_generate_kwargs["reasoning_budget_tokens"] == expected_budget
    assert fake.last_generate_kwargs["history"] is None
    assert fake.last_generate_kwargs["system_instruction"] == "Reply in one sentence."
    response_schema = fake.last_generate_kwargs["response_schema"]
    assert isinstance(response_schema, dict)
    assert response_schema["type"] == "object"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompts", "expected_implicit_caching"),
    [
        (("Q1?",), True),
        (("Q1?", "Q2?"), False),
    ],
    ids=["single_call_on", "multi_call_off"],
)
async def test_implicit_caching_default_heuristic(
    monkeypatch: pytest.MonkeyPatch,
    prompts: tuple[str, ...],
    expected_implicit_caching: bool,  # noqa: FBT001
) -> None:
    """Single-call defaults implicit caching on; multi-call defaults it off."""
    fake = KwargsCaptureProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=False,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=False,
            implicit_caching=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="anthropic", model=ANTHROPIC_MODEL, use_mock=True)

    await pollux.run_many(prompts, config=cfg)

    assert len(fake.generate_kwargs) == len(prompts)
    assert all(
        call["request"].implicit_caching is expected_implicit_caching
        for call in fake.generate_kwargs
    )


@pytest.mark.asyncio
async def test_implicit_caching_requires_provider_capability_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit implicit_caching=True should fail on providers that lack it."""
    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match="implicit caching") as exc:
        await pollux.run(
            "Q1?",
            config=cfg,
            options=Options(implicit_caching=True),
        )

    assert exc.value.hint is not None


@pytest.mark.asyncio
async def test_anthropic_preflight_rejects_reasoning_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real AnthropicProvider rejects reasoning on Claude 3 via validate_request.

    Proves the pipeline runs the ValidatingProvider pre-flight before any
    network call: the provider has no usable client, so a non-failing path
    would error differently than this ConfigurationError.
    """
    provider = AnthropicProvider("test-key")
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)
    cfg = Config(
        provider="anthropic", model="claude-3-5-sonnet-20241022", use_mock=True
    )

    with pytest.raises(ConfigurationError, match="extended thinking"):
        await pollux.run(
            "Think hard.", config=cfg, options=Options(reasoning_effort="high")
        )
