"""Integration tests for the interact() v2 frontdoor."""

from __future__ import annotations

from pydantic import BaseModel
import pytest

import pollux
from pollux import Environment, Input, Output, ToolDeclaration, ToolResult, interact
from pollux.config import Config
from pollux.providers.base import ProviderCapabilities, ProviderReadiness
from pollux.providers.models import ProviderResponse
from pollux.providers.models import ToolCall as ProviderToolCall
from tests.conftest import ANTHROPIC_MODEL, FakeProvider
from tests.helpers import ScriptedProvider

pytestmark = pytest.mark.integration


def _cfg() -> Config:
    return Config(provider="anthropic", model=ANTHROPIC_MODEL, use_mock=True)


class _Weather(BaseModel):
    value: int


@pytest.mark.asyncio
async def test_interact_returns_output(monkeypatch):
    provider = ScriptedProvider(
        script=[
            ProviderResponse(text="hi", usage={"total_tokens": 3}, finish_reason="stop")
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    out = await interact(
        Environment(instructions="sys"), Input("Hello?"), config=_cfg()
    )

    assert isinstance(out, Output)
    assert out.text == "hi"
    assert out.metrics.completion_status == "clean"


@pytest.mark.asyncio
async def test_first_class_kwargs_reach_the_provider(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    await interact(
        Environment(instructions="sys"), Input("Q"), config=_cfg(), temperature=0.25
    )

    assert provider.last_generate_kwargs is not None
    assert provider.last_generate_kwargs["temperature"] == 0.25
    assert provider.last_generate_kwargs["system_instruction"] == "sys"


@pytest.mark.asyncio
async def test_structured_output(monkeypatch):
    provider = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=False, uploads=False, structured_outputs=True
        ),
        script=[
            ProviderResponse(
                text="", usage={}, structured={"value": 7}, finish_reason="stop"
            )
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    out = await interact(Environment(), Input("Q"), config=_cfg(), output=_Weather)

    assert isinstance(out.structured, _Weather)
    assert out.structured.value == 7


@pytest.mark.asyncio
async def test_agent_loop_continues_from_tool_results(monkeypatch):
    provider = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True, uploads=True, conversation=True
        ),
        script=[
            ProviderResponse(
                text="",
                usage={"total_tokens": 1},
                tool_calls=[
                    ProviderToolCall(
                        id="c1", name="get_weather", arguments='{"city": "P"}'
                    )
                ],
                response_id="r1",
                finish_reason="tool_calls",
            ),
            ProviderResponse(
                text="It is sunny.", usage={"total_tokens": 2}, finish_reason="stop"
            ),
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)
    env = Environment(
        instructions="sys",
        tools=[ToolDeclaration(name="get_weather", description="Get weather")],
    )

    first = await interact(env, Input("Weather in Paris?"), config=_cfg())
    assert first.tool_calls[0].name == "get_weather"
    assert first.continuation is not None

    results = [
        ToolResult(call_id=call.id, content="sunny") for call in first.tool_calls
    ]
    final = await interact(
        env,
        Input(continuation=first.continuation, tool_results=results),
        config=_cfg(),
    )
    assert final.text == "It is sunny."
    assert not final.tool_calls


@pytest.mark.asyncio
async def test_session_reuses_provider_and_closes(monkeypatch):
    class CloseableScriptedProvider(ScriptedProvider):
        closed: bool = False

        async def aclose(self) -> None:
            self.closed = True

    provider = CloseableScriptedProvider(
        script=[
            ProviderResponse(text="one", usage={"total_tokens": 1}),
            ProviderResponse(text="two", usage={"total_tokens": 1}),
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    async with pollux.Session(_cfg()) as session:
        first = await session.interact(Environment(), Input("Q1"))
        second = await session.interact(Environment(), Input("Q2"))

    assert first.text == "one"
    assert second.text == "two"
    assert provider.generate_calls == 2
    assert provider.closed is True


@pytest.mark.asyncio
async def test_session_check_ready_uses_provider_probe(monkeypatch):
    class ReadyProvider(ScriptedProvider):
        async def check_ready(self, *, model: str | None = None) -> ProviderReadiness:
            return ProviderReadiness(
                ready=True, provider="anthropic", model=model, message="ok"
            )

    provider = ReadyProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    readiness = await pollux.check_ready(_cfg())

    assert readiness.ready is True
    assert readiness.model == ANTHROPIC_MODEL


def test_local_reasoning_returns_scoped_provider_options() -> None:
    assert pollux.local_reasoning(enabled=False) == {
        "local": {"chat_template_kwargs": {"enable_thinking": False}}
    }
