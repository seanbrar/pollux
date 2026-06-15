"""Integration tests for the v2 execution path.

These run the v2 `execute_interaction(s)` path through provider doubles and assert
it produces `Output`/`OutputCollection` natively.
"""

from __future__ import annotations

import pytest

import pollux
from pollux.config import Config
from pollux.interaction.environment import Environment
from pollux.interaction.execute import execute_interaction, execute_interactions
from pollux.interaction.input import Input
from pollux.interaction.output import Output
from pollux.interaction.requirements import OutputRequirements
from pollux.providers.models import ProviderResponse, ToolCall
from tests.conftest import ANTHROPIC_MODEL, FakeProvider
from tests.helpers import ScriptedProvider

pytestmark = pytest.mark.integration


def _cfg() -> Config:
    return Config(provider="anthropic", model=ANTHROPIC_MODEL, use_mock=True)


@pytest.mark.asyncio
async def test_execute_interaction_produces_output():
    provider = ScriptedProvider(
        script=[
            ProviderResponse(
                text="The answer.",
                usage={"input_tokens": 3, "total_tokens": 8},
                finish_reason="stop",
            )
        ]
    )
    out = await execute_interaction(
        Environment(instructions="sys"),
        Input(content="Q"),
        OutputRequirements(),
        _cfg(),
        provider,
    )
    assert out.text == "The answer."
    assert out.usage.total_tokens == 8
    assert out.metrics.completion_status == "clean"


@pytest.mark.asyncio
async def test_run_frontdoor_returns_output(monkeypatch):
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

    out = await pollux.run("Q", config=_cfg())

    assert isinstance(out, Output)
    assert out.text == "The answer."
    assert out.usage.total_tokens == 8
    assert out.metrics.completion_status == "clean"


@pytest.mark.asyncio
async def test_tool_calls_and_continuation():
    provider = ScriptedProvider(
        script=[
            ProviderResponse(
                text="",
                usage={"total_tokens": 2},
                tool_calls=[
                    ToolCall(id="c1", name="get_weather", arguments='{"city": "P"}')
                ],
                response_id="r1",
                finish_reason="tool_calls",
            )
        ]
    )
    out = await execute_interaction(
        Environment(), Input(content="Weather?"), OutputRequirements(), _cfg(), provider
    )
    assert out.tool_calls[0].name == "get_weather"
    assert out.tool_calls[0].arguments == {"city": "P"}
    assert out.metrics.completion_status == "clean"
    assert out.continuation is not None
    assert any(message.tool_calls for message in out.continuation.messages)


@pytest.mark.asyncio
async def test_execute_interactions_collection():
    provider = FakeProvider()
    collection = await execute_interactions(
        Environment(),
        [Input(content="Q1"), Input(content="Q2")],
        OutputRequirements(),
        _cfg(),
        provider,
    )
    assert collection.answers == ["ok:Q1", "ok:Q2"]
    assert collection.status == "ok"
    assert len(collection.outputs) == 2
