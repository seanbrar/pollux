"""Pipeline boundary tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
import pytest

import pollux
import pollux.cache
from pollux.config import Config
from pollux.options import Options
from pollux.providers.base import (
    ProviderCapabilities,
)
from pollux.providers.models import (
    ProviderRequest,
    ProviderResponse,
)
from tests.conftest import (
    GEMINI_MODEL,
    FakeProvider,
)
from tests.helpers import ScriptedProvider

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_structured_output_returns_pydantic_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structured outputs should validate into model instances when requested."""

    class Paper(BaseModel):
        title: str
        findings: list[str]

    @dataclass
    class _StructuredProvider(FakeProvider):
        _capabilities: ProviderCapabilities = field(
            default_factory=lambda: ProviderCapabilities(
                persistent_cache=True,
                uploads=True,
                structured_outputs=True,
                reasoning=False,
                deferred_delivery=False,
                conversation=False,
            )
        )

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            assert isinstance(request.response_schema, dict)
            return ProviderResponse(
                text='{"title":"A","findings":["x","y"]}',
                structured={"title": "A", "findings": ["x", "y"]},
                usage={"total_tokens": 1},
            )

    fake = _StructuredProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run(
        "Extract",
        config=cfg,
        options=Options(response_schema=Paper),
    )

    assert result["answers"] == ['{"title":"A","findings":["x","y"]}']
    assert "structured" in result
    structured = result["structured"]
    assert isinstance(structured, list)
    assert len(structured) == 1
    assert isinstance(structured[0], Paper)
    assert structured[0].title == "A"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("script", "expected_status", "expected_answers"),
    [
        (
            [
                {"text": "ok", "usage": {"total_tokens": 1}},
                {"text": "", "usage": {"total_tokens": 1}},
            ],
            "partial",
            ["ok", ""],
        ),
        (
            [
                {"text": "", "usage": {"total_tokens": 1}},
                {"text": "", "usage": {"total_tokens": 1}},
            ],
            "error",
            ["", ""],
        ),
    ],
)
async def test_result_status_classification(
    monkeypatch: pytest.MonkeyPatch,
    script: list[dict[str, Any]],
    expected_status: str,
    expected_answers: list[str],
) -> None:
    """Status classification should be stable across refactors."""
    fake = ScriptedProvider(script=list(script))
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run_many(("A", "B"), config=cfg)

    assert result["status"] == expected_status
    assert result["answers"] == expected_answers


@pytest.mark.asyncio
async def test_finish_reasons_forwarded_to_result_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider finish_reason should appear in metrics.finish_reasons."""
    fake = ScriptedProvider(
        script=[
            ProviderResponse(
                text="The answer.", usage={"total_tokens": 5}, finish_reason="stop"
            ),
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run("What?", config=cfg)

    assert result["metrics"]["finish_reasons"] == ["stop"]


@pytest.mark.asyncio
async def test_finish_reasons_none_when_provider_omits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """finish_reasons should contain None when provider does not report it."""
    fake = ScriptedProvider(
        script=[
            ProviderResponse(text="ok", usage={"total_tokens": 1}),
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run("What?", config=cfg)

    assert result["metrics"]["finish_reasons"] == [None]


@pytest.mark.asyncio
async def test_structured_validation_failure_returns_none_in_structured_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When structured payload fails validation, keep answers but set structured=None."""

    class Paper(BaseModel):
        title: str
        year: int

    fake = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=True,
            reasoning=False,
            deferred_delivery=False,
            conversation=False,
        ),
        script=[
            ProviderResponse(
                text='{"title":"A"}',
                structured={"title": "A"},
                usage={"total_tokens": 1},
            )
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run(
        "Extract",
        config=cfg,
        options=Options(response_schema=Paper),
    )

    assert result["answers"] == ['{"title":"A"}']
    assert result["structured"] == [None]


# =============================================================================
# Reasoning / Thinking (v1.2)
# =============================================================================


@pytest.mark.asyncio
async def test_reasoning_surfaced_in_result_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider reasoning text should appear in ResultEnvelope.reasoning."""
    fake = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            reasoning=True,
        ),
        script=[
            {
                "text": "The answer is 42.",
                "usage": {"total_tokens": 10},
                "reasoning": "Let me think step by step...",
            },
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run(
        "What is the meaning of life?",
        config=cfg,
        options=Options(reasoning_effort="high"),
    )

    assert result["answers"] == ["The answer is 42."]
    assert result["reasoning"] == ["Let me think step by step..."]


@pytest.mark.asyncio
async def test_reasoning_omitted_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ResultEnvelope should not include reasoning key when provider omits it."""
    fake = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            reasoning=True,
        ),
        script=[
            {"text": "Hello.", "usage": {"total_tokens": 5}},
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run("Hi", config=cfg)

    assert "reasoning" not in result


@pytest.mark.asyncio
async def test_reasoning_mixed_across_multi_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-prompt: reasoning=None for calls without thinking content."""
    fake = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            reasoning=True,
        ),
        script=[
            {
                "text": "Answer 1",
                "usage": {"total_tokens": 5},
                "reasoning": "Thought A",
            },
            {"text": "Answer 2", "usage": {"total_tokens": 5}},
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run_many(("Q1?", "Q2?"), config=cfg)

    assert result["answers"] == ["Answer 1", "Answer 2"]
    assert result["reasoning"] == ["Thought A", None]


@pytest.mark.asyncio
async def test_reasoning_tokens_aggregate_in_result_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pipeline should preserve and sum reasoning_tokens across calls."""
    fake = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            reasoning=True,
        ),
        script=[
            {
                "text": "Answer 1",
                "usage": {"total_tokens": 8, "reasoning_tokens": 3},
            },
            {
                "text": "Answer 2",
                "usage": {"total_tokens": 9, "reasoning_tokens": 5},
            },
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run_many(
        ("Q1?", "Q2?"),
        config=cfg,
        options=Options(reasoning_effort="high"),
    )

    assert result["usage"]["reasoning_tokens"] == 8
    assert result["usage"]["total_tokens"] == 17


@pytest.mark.asyncio
async def test_cached_tokens_aggregate_across_fanout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cached_tokens should sum across fan-out calls like other usage keys."""
    fake = ScriptedProvider(
        script=[
            {
                "text": "A1",
                "usage": {
                    "input_tokens": 10_000,
                    "output_tokens": 20,
                    "total_tokens": 10_020,
                    "cached_tokens": 0,
                },
            },
            {
                "text": "A2",
                "usage": {
                    "input_tokens": 10_000,
                    "output_tokens": 20,
                    "total_tokens": 10_020,
                    "cached_tokens": 9_500,
                },
            },
            {
                "text": "A3",
                "usage": {
                    "input_tokens": 10_000,
                    "output_tokens": 20,
                    "total_tokens": 10_020,
                    "cached_tokens": 9_500,
                },
            },
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run_many(("Q1?", "Q2?", "Q3?"), config=cfg)

    assert result["usage"]["cached_tokens"] == 19_000
    assert result["usage"]["input_tokens"] == 30_000
    # Per-call values remain accessible under diagnostics for anyone who needs
    # the per-prompt view (e.g., spotting which call missed the cache).
    per_call = [r["usage"] for r in result["diagnostics"]["raw_responses"]]
    assert [u.get("cached_tokens") for u in per_call] == [0, 9_500, 9_500]


@pytest.mark.asyncio
async def test_cached_tokens_absent_when_provider_omits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cached_tokens should not appear when no provider response reports it."""
    fake = ScriptedProvider(
        script=[
            {"text": "A1", "usage": {"input_tokens": 10, "total_tokens": 15}},
            {"text": "A2", "usage": {"input_tokens": 10, "total_tokens": 15}},
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run_many(("Q1?", "Q2?"), config=cfg)

    assert "cached_tokens" not in result["usage"]
