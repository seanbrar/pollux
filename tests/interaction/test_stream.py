"""Coverage for the v2 streaming path: event timeline and assembled output.

These exercise core's ``stream_interaction`` assembly (event vocabulary, tool-call
fragment reassembly, ``done.output`` parity with non-streaming) and the public
``stream()`` frontdoor, driven by provider doubles rather than the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

import pollux
from pollux import Environment, Event, Input
from pollux.config import Config
from pollux.errors import APIError, ConfigurationError
from pollux.interaction.execute import execute_interaction, stream_interaction
from pollux.interaction.requirements import OutputRequirements
from pollux.interaction.tools import ToolCallDelta
from pollux.providers.base import ProviderCapabilities
from pollux.providers.mock import MockProvider
from pollux.providers.models import ProviderResponse, ProviderStreamChunk
from tests.conftest import ANTHROPIC_MODEL, FakeProvider

pytestmark = pytest.mark.integration


def _cfg() -> Config:
    return Config(provider="anthropic", model=ANTHROPIC_MODEL, use_mock=True)


@dataclass
class StreamScriptProvider:
    """Provider double that streams a scripted list of chunks.

    ``raise_at`` makes ``stream_generate`` raise after yielding that many chunks,
    standing in for a mid-stream provider failure.
    """

    chunks: list[ProviderStreamChunk] = field(default_factory=list)
    raise_at: int | None = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            persistent_cache=False,
            uploads=False,
            structured_outputs=True,
            conversation=True,
        )

    async def generate(self, *_args: Any) -> ProviderResponse:  # pragma: no cover
        raise AssertionError("stream tests must not call generate()")

    async def stream_generate(
        self, snapshot: Any, input: Any, requirements: Any, config: Any
    ) -> Any:
        del snapshot, input, requirements, config
        for position, chunk in enumerate(self.chunks):
            if self.raise_at is not None and position == self.raise_at:
                raise APIError("stream exploded", provider="test", phase="stream")
            yield chunk


async def _collect(
    environment: Environment,
    input_: Input,
    provider: Any,
    requirements: OutputRequirements | None = None,
) -> list[Event]:
    requirements = requirements or OutputRequirements()
    return [
        event
        async for event in stream_interaction(
            environment, input_, requirements, _cfg(), provider
        )
    ]


@pytest.mark.asyncio
async def test_stream_event_timeline_and_done_matches_nonstreaming() -> None:
    """The mock stream yields start/text/usage/finish/done; done == generate()."""
    events = await _collect(Environment(), Input("hello world"), MockProvider())

    assert [e.type for e in events] == [
        "start",
        "text_delta",
        "text_delta",
        "usage",
        "finish",
        "done",
    ]
    streamed_text = "".join(e.text for e in events if e.type == "text_delta")
    done = events[-1]
    assert done.output is not None
    assert streamed_text == done.output.text

    nonstreaming = await execute_interaction(
        Environment(),
        Input("hello world"),
        OutputRequirements(),
        _cfg(),
        MockProvider(),
    )
    assert done.output.text == nonstreaming.text
    assert done.output.usage.to_jsonable() == nonstreaming.usage.to_jsonable()


@pytest.mark.asyncio
async def test_stream_assembles_tool_call_fragments() -> None:
    """Streamed tool-call fragments reassemble into one parsed ToolCall."""
    provider = StreamScriptProvider(
        chunks=[
            ProviderStreamChunk(text="Let me check. "),
            ProviderStreamChunk(
                tool_calls=(ToolCallDelta(index=0, id="call_1", name="get_weather"),)
            ),
            ProviderStreamChunk(
                tool_calls=(ToolCallDelta(index=0, arguments='{"city":'),)
            ),
            ProviderStreamChunk(
                tool_calls=(ToolCallDelta(index=0, arguments='"NYC"}'),)
            ),
            ProviderStreamChunk(
                usage={"input_tokens": 5, "total_tokens": 9},
                finish_reason="tool_calls",
                response_id="r1",
            ),
        ]
    )

    events = await _collect(Environment(), Input("Weather in NYC?"), provider)

    assert [e.type for e in events] == [
        "start",
        "text_delta",
        "tool_call_delta",
        "tool_call_delta",
        "tool_call_delta",
        "usage",
        "tool_call",
        "finish",
        "done",
    ]

    completed = next(e for e in events if e.type == "tool_call")
    assert completed.tool_call is not None
    assert completed.tool_call.name == "get_weather"
    assert completed.tool_call.arguments_text == '{"city":"NYC"}'
    assert completed.tool_call.arguments == {"city": "NYC"}

    done = events[-1].output
    assert done is not None
    assert done.text == "Let me check. "
    assert len(done.tool_calls) == 1
    assert done.tool_calls[0].arguments == {"city": "NYC"}
    assert done.metrics.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_stream_accumulates_reasoning() -> None:
    """reasoning_delta events accumulate into done.output.reasoning."""
    provider = StreamScriptProvider(
        chunks=[
            ProviderStreamChunk(reasoning="think"),
            ProviderStreamChunk(reasoning="ing..."),
            ProviderStreamChunk(text="42"),
            ProviderStreamChunk(finish_reason="stop"),
        ]
    )

    events = await _collect(Environment(), Input("2+2?"), provider)

    reasoning = "".join(e.text for e in events if e.type == "reasoning_delta")
    assert reasoning == "thinking..."
    done = events[-1].output
    assert done is not None
    assert done.reasoning == "thinking..."
    assert done.text == "42"


@pytest.mark.asyncio
async def test_stream_rejects_non_streaming_provider() -> None:
    """A provider without stream_generate fails fast before any event."""
    with pytest.raises(ConfigurationError, match="does not support streaming"):
        await _collect(Environment(), Input("hi"), FakeProvider())


@pytest.mark.asyncio
async def test_stream_midstream_error_propagates_without_done() -> None:
    """A mid-stream failure raises and never emits a done event."""
    provider = StreamScriptProvider(
        chunks=[
            ProviderStreamChunk(text="partial"),
            ProviderStreamChunk(text="never reached"),
        ],
        raise_at=1,
    )

    seen: list[str] = []
    with pytest.raises(APIError, match="stream exploded"):
        async for event in stream_interaction(
            Environment(), Input("hi"), OutputRequirements(), _cfg(), provider
        ):
            seen.append(event.type)

    assert "done" not in seen
    assert seen == ["start", "text_delta"]


@pytest.mark.asyncio
async def test_stream_frontdoor_yields_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """pollux.stream() drives the streaming provider and closes it after."""
    provider = StreamScriptProvider(
        chunks=[
            ProviderStreamChunk(text="hi"),
            ProviderStreamChunk(finish_reason="stop", usage={"total_tokens": 2}),
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    types = [
        event.type
        async for event in pollux.stream(
            Environment(instructions="sys"), Input("Hello?"), config=_cfg()
        )
    ]

    assert types == ["start", "text_delta", "usage", "finish", "done"]
