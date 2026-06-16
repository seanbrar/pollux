"""OpenAI streaming contract: Responses API event mapping and assembly."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pollux import Environment, Input
from pollux.config import Config
from pollux.errors import APIError
from pollux.interaction.execute import stream_interaction
from pollux.interaction.requirements import OutputRequirements
from pollux.interaction.tools import ToolDeclaration
from pollux.providers.openai import OpenAIProvider
from tests.conftest import OPENAI_MODEL
from tests.helpers import make_interaction

pytestmark = pytest.mark.contract


def _openai(**kwargs: Any) -> tuple[Any, Any, Any, Any]:
    kwargs.setdefault("model", OPENAI_MODEL)
    return make_interaction(provider="openai", **kwargs)


def _event(type_: str, **kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(type=type_, **kwargs)


def _completed_response() -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        output_tokens_details=None,
        input_tokens_details=None,
    )
    return SimpleNamespace(
        output_text="Hello",
        usage=usage,
        id="resp_1",
        output=[],
        status="completed",
        incomplete_details=None,
    )


def _text_and_tool_events() -> list[SimpleNamespace]:
    return [
        _event("response.created", response=SimpleNamespace(id="resp_1")),
        _event("response.output_text.delta", delta="Hel"),
        _event("response.reasoning_summary_text.delta", delta="thinking"),
        _event("response.output_text.delta", delta="lo"),
        _event(
            "response.output_item.added",
            output_index=1,
            item=SimpleNamespace(
                type="function_call", call_id="call_1", name="get_weather"
            ),
        ),
        _event(
            "response.function_call_arguments.delta", output_index=1, delta='{"city":'
        ),
        _event(
            "response.function_call_arguments.delta", output_index=1, delta='"NYC"}'
        ),
        _event("response.completed", response=_completed_response()),
    ]


class _AsyncEvents:
    def __init__(
        self, events: list[SimpleNamespace], raise_exc: Exception | None = None
    ):
        self._events = events
        self._raise = raise_exc

    def __aiter__(self) -> _AsyncEvents:
        return self

    async def __anext__(self) -> SimpleNamespace:
        if self._raise is not None:
            raise self._raise
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


class _FakeResponses:
    def __init__(
        self, events: list[SimpleNamespace], raise_exc: Exception | None = None
    ):
        self._events = events
        self._raise = raise_exc
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> _AsyncEvents:
        self.last_kwargs = kwargs
        return _AsyncEvents(self._events, raise_exc=self._raise)


def _provider_with(
    events: list[SimpleNamespace], raise_exc: Exception | None = None
) -> tuple[OpenAIProvider, _FakeResponses]:
    responses = _FakeResponses(events, raise_exc=raise_exc)
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"responses": responses})()
    return provider, responses


@pytest.mark.asyncio
async def test_openai_stream_through_interaction_assembles_output() -> None:
    """Responses stream events assemble into the same Output as generate()."""
    provider, responses = _provider_with(_text_and_tool_events())
    config = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)
    environment = Environment(
        tools=[
            ToolDeclaration(
                name="get_weather",
                description="Get weather",
                parameters={
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            )
        ]
    )

    events = [
        event
        async for event in stream_interaction(
            environment, Input("Weather?"), OutputRequirements(), config, provider
        )
    ]

    assert responses.last_kwargs is not None
    assert responses.last_kwargs["stream"] is True

    types = [e.type for e in events]
    assert types[0] == "start"
    assert "reasoning_delta" in types
    assert "tool_call" in types
    assert types[-1] == "done"

    done = events[-1].output
    assert done is not None
    assert done.text == "Hello"
    assert done.reasoning == "thinking"
    assert done.tool_calls[0].name == "get_weather"
    assert done.tool_calls[0].arguments == {"city": "NYC"}
    assert done.usage.total_tokens == 15
    assert done.metrics.finish_reason == "completed"


@pytest.mark.asyncio
async def test_openai_stream_error_raises_api_error() -> None:
    """A failure mid-stream surfaces as an APIError attributed to openai."""
    provider, _responses = _provider_with([], raise_exc=RuntimeError("boom"))

    with pytest.raises(APIError) as exc:
        async for _chunk in provider.stream_generate(*_openai(content="Hi")):
            pass

    assert exc.value.provider == "openai"
    assert exc.value.phase == "stream"
