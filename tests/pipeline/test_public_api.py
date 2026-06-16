"""Pipeline boundary tests."""

from __future__ import annotations

import pytest

import pollux
import pollux.cache
from pollux.config import Config
from pollux.errors import ConfigurationError
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


@pytest.mark.asyncio
async def test_empty_string_prompt_raises_clear_error() -> None:
    """An empty string prompt is a caller mistake; must fail fast."""
    config = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match="no user content") as exc:
        await pollux.run("", config=config)
    assert exc.value.hint is not None


def test_requirements_reject_unknown_provider_options_provider() -> None:
    """provider_options should be keyed by supported provider names."""
    with pytest.raises(ConfigurationError, match="Unknown provider_options provider"):
        pollux.OutputRequirements(provider_options={"not-a-provider": {"x": 1}})


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
