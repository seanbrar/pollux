"""Pipeline boundary tests."""

from __future__ import annotations

import pytest

import pollux
import pollux.cache
from pollux.config import Config
from pollux.errors import (
    ConfigurationError,
    SourceError,
)
from pollux.options import Options
from pollux.request import normalize_request
from pollux.source import Source
from tests.conftest import (
    GEMINI_MODEL,
    OPENAI_MODEL,
    FakeProvider,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_run_and_run_many_smoke() -> None:
    """Smoke: public API returns Output / OutputCollection."""
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with_source = await pollux.run(
        "Summarize this text",
        source=Source.from_text("hello world"),
        config=cfg,
    )

    assert with_source.text == "echo: hello world"
    assert with_source.metrics.completion_status == "clean"

    prompt_only = await pollux.run("What is 2+2?", config=cfg)
    assert prompt_only.text

    many = await pollux.run_many(
        prompts=("Q1?", "Q2?"),
        sources=(Source.from_text("shared context"),),
        config=cfg,
    )

    assert many.status == "ok"
    assert len(many.outputs) == 2

    empty = await pollux.run_many(prompts=[], config=cfg)
    assert empty.status == "ok"
    assert empty.answers == []
    assert len(empty.outputs) == 0


# =============================================================================
# Public API Boundary: Error Paths
# =============================================================================


def test_empty_string_prompt_raises_clear_error() -> None:
    """An empty string prompt is a caller mistake; must fail fast."""
    config = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match="empty or whitespace") as exc:
        normalize_request("", sources=(), config=config)
    assert exc.value.hint is not None


def test_whitespace_only_prompt_raises_clear_error() -> None:
    """A whitespace-only prompt is a caller mistake; must fail fast."""
    config = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match="empty or whitespace") as exc:
        normalize_request("   \n\t  ", sources=(), config=config)
    assert exc.value.hint is not None


def test_batch_with_one_empty_prompt_identifies_index() -> None:
    """In a multi-prompt batch, the error should identify which prompt is bad."""
    config = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match=r"prompts\[1\]") as exc:
        normalize_request(["good prompt", ""], sources=(), config=config)
    assert exc.value.hint is not None


def test_empty_prompt_list_is_valid_noop() -> None:
    """run_many(prompts=[]) is a valid no-op; must not raise."""
    config = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    req = normalize_request([], sources=(), config=config)
    assert req.prompts == ()


def test_request_rejects_non_source_objects() -> None:
    """Source inputs must be explicit Source objects."""
    config = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(SourceError) as exc:
        normalize_request("hello", sources=["not-a-source"], config=config)  # type: ignore[list-item]

    assert "Expected Source" in str(exc.value)
    assert exc.value.hint is not None


def test_options_reject_unknown_provider_options_provider() -> None:
    """provider_options should be keyed by supported provider names."""
    with pytest.raises(ConfigurationError, match="Unknown provider_options provider"):
        Options(provider_options={"not-a-provider": {"x": 1}})


@pytest.mark.asyncio
async def test_provider_options_are_forwarded_for_active_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execution should pass only the active provider's raw options."""
    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config, _p=fake: _p)

    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)
    await pollux.run(
        "Hello",
        config=cfg,
        provider_options={
            "openai": {"seed": 123},
            "gemini": {"seed": 456},
        },
    )

    assert fake.last_generate_kwargs is not None
    assert fake.last_generate_kwargs["provider_options"] == {"seed": 123}
