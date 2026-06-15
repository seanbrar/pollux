"""Integration tests for the run()/run_many() v2 frontdoors.

After the Slice 3b flip, run() returns an Output and run_many() returns an
OutputCollection. These cover the friendly facade end to end (the v1
ResultEnvelope-shape tests they replace lived in tests/pipeline).
"""

from __future__ import annotations

from pydantic import BaseModel
import pytest

import pollux
from pollux.config import Config
from pollux.interaction.collection import OutputCollection
from pollux.interaction.output import Output
from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import ProviderResponse
from tests.conftest import ANTHROPIC_MODEL, FakeProvider
from tests.helpers import ScriptedProvider

pytestmark = pytest.mark.integration


def _cfg() -> Config:
    return Config(provider="anthropic", model=ANTHROPIC_MODEL, use_mock=True)


class _Answer(BaseModel):
    value: int


@pytest.mark.asyncio
async def test_run_returns_single_output(monkeypatch):
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: FakeProvider())
    out = await pollux.run("Hi?", config=_cfg())
    assert isinstance(out, Output)
    assert out.text == "ok:Hi?"


@pytest.mark.asyncio
async def test_run_many_returns_collection_in_order(monkeypatch):
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: FakeProvider())
    coll = await pollux.run_many(["A", "B", "C"], config=_cfg())
    assert isinstance(coll, OutputCollection)
    assert coll.answers == ["ok:A", "ok:B", "ok:C"]
    assert coll.status == "ok"


@pytest.mark.asyncio
async def test_run_many_partial_status_from_empty_answers(monkeypatch):
    provider = ScriptedProvider(
        script=[
            ProviderResponse(
                text="A1", usage={"total_tokens": 1}, finish_reason="stop"
            ),
            ProviderResponse(text="", usage={"total_tokens": 1}, finish_reason="stop"),
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)
    coll = await pollux.run_many(["Q1", "Q2"], config=_cfg())
    assert coll.status == "partial"


@pytest.mark.asyncio
async def test_run_first_class_kwargs_reach_provider(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)
    await pollux.run("Q", config=_cfg(), instructions="sys", temperature=0.0)
    assert provider.last_generate_kwargs is not None
    assert provider.last_generate_kwargs["temperature"] == 0.0
    assert provider.last_generate_kwargs["system_instruction"] == "sys"


@pytest.mark.asyncio
async def test_run_structured_output(monkeypatch):
    provider = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=False, uploads=False, structured_outputs=True
        ),
        script=[
            ProviderResponse(
                text="", usage={}, structured={"value": 5}, finish_reason="stop"
            )
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)
    out = await pollux.run("Q", config=_cfg(), output=_Answer)
    assert isinstance(out.structured, _Answer)
    assert out.structured.value == 5


@pytest.mark.asyncio
async def test_run_with_source_shares_context(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)
    out = await pollux.run(
        "Summarize", source=pollux.Source.from_text("DOCBODY"), config=_cfg()
    )
    # FakeProvider echoes the first non-empty string part (the source text).
    assert isinstance(out, Output)
    assert provider.last_parts is not None
    assert "DOCBODY" in provider.last_parts


@pytest.mark.asyncio
async def test_reasoning_and_usage_aggregate_across_fan_out(monkeypatch):
    provider = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=False, uploads=False, reasoning=True
        ),
        script=[
            ProviderResponse(
                text="A1",
                usage={"total_tokens": 4, "reasoning_tokens": 2, "cached_tokens": 1},
                reasoning="because one",
                finish_reason="stop",
            ),
            ProviderResponse(
                text="A2",
                usage={"total_tokens": 6, "reasoning_tokens": 3, "cached_tokens": 2},
                finish_reason="stop",
            ),
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)
    coll = await pollux.run_many(["Q1", "Q2"], config=_cfg())

    assert [o.reasoning for o in coll.outputs] == ["because one", None]
    assert coll.usage.reasoning_tokens == 5
    assert coll.usage.cached_tokens == 3
    assert coll.usage.total_tokens == 10


@pytest.mark.asyncio
async def test_implicit_caching_reflected_in_metrics(monkeypatch):
    provider = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=False, uploads=False, implicit_caching=True
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)
    out = await pollux.run("Q", config=_cfg())
    assert out.metrics.cache_mode == "implicit"
