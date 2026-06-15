"""Equivalence tests: v2 types losslessly represent today's pipeline output.

These run the real mock-provider pipeline, then convert the resulting
``ResultEnvelope`` through the transitional adapters and assert the v2 facets
match. This is the proof backing the Slice 1 types before the provider boundary
is migrated in Slice 2.
"""

from __future__ import annotations

import pytest

import pollux
from pollux.config import Config
from pollux.interaction.adapters import (
    collection_from_envelope,
    output_from_envelope,
)
from pollux.providers.models import ProviderResponse, ToolCall
from tests.conftest import GEMINI_MODEL
from tests.helpers import ScriptedProvider

pytestmark = pytest.mark.integration


def _mock_cfg() -> Config:
    return Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)


@pytest.mark.asyncio
async def test_single_output_matches_envelope(monkeypatch):
    fake = ScriptedProvider(
        script=[
            ProviderResponse(
                text="The answer.",
                usage={"input_tokens": 3, "total_tokens": 8},
                finish_reason="stop",
            )
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    envelope = await pollux.run("What?", config=_mock_cfg())
    output = output_from_envelope(envelope)

    assert output.text == envelope["answers"][0]
    assert output.usage.input_tokens == 3
    assert output.usage.total_tokens == 8
    assert output.metrics.finish_reason == "stop"
    assert output.metrics.completion_status == "clean"

    payload = output.to_jsonable()
    assert "confidence" not in payload
    assert "status" not in payload
    assert "extraction_method" not in payload


@pytest.mark.asyncio
async def test_tool_calls_and_continuation_survive_conversion(monkeypatch):
    fake = ScriptedProvider(
        script=[
            ProviderResponse(
                text="",
                usage={"total_tokens": 2},
                tool_calls=[
                    ToolCall(id="call_1", name="get_weather", arguments='{"city": "P"}')
                ],
                response_id="resp_1",
                finish_reason="tool_calls",
            )
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    envelope = await pollux.run("Weather?", config=_mock_cfg())
    output = output_from_envelope(envelope)

    assert len(output.tool_calls) == 1
    call = output.tool_calls[0]
    assert call.id == "call_1"
    assert call.name == "get_weather"
    assert call.arguments == {"city": "P"}
    assert call.arguments_error is None
    assert output.metrics.completion_status == "clean"

    assert output.continuation is not None
    assert any(message.tool_calls for message in output.continuation.messages)


@pytest.mark.asyncio
async def test_collection_matches_envelope(monkeypatch):
    fake = ScriptedProvider(
        script=[
            ProviderResponse(
                text="A1", usage={"total_tokens": 1}, finish_reason="stop"
            ),
            ProviderResponse(
                text="A2", usage={"total_tokens": 2}, finish_reason="stop"
            ),
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    envelope = await pollux.run_many(("Q1", "Q2"), config=_mock_cfg())
    collection = collection_from_envelope(envelope)

    assert collection.answers == envelope["answers"]
    assert collection.status == envelope["status"]
    assert len(collection.outputs) == 2
    assert collection.usage.total_tokens == envelope["usage"]["total_tokens"]
