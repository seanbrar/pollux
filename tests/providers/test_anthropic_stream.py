"""Anthropic streaming contract: event mapping and signed thinking-block replay.

The load-bearing case is reassembling signed ``thinking`` blocks from the stream:
Anthropic requires them replayed verbatim when continuing an extended-thinking +
tool turn, so a streamed turn must surface them in provider_state exactly like the
non-streaming path.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from pollux import Environment, Input
from pollux.config import Config
from pollux.errors import APIError
from pollux.interaction.execute import stream_interaction
from pollux.interaction.requirements import OutputRequirements
from pollux.interaction.tools import ToolDeclaration
from pollux.providers.anthropic import AnthropicProvider
from tests.conftest import ANTHROPIC_MODEL
from tests.helpers import make_interaction

pytestmark = pytest.mark.contract


def _anthropic(**kwargs: Any) -> tuple[Any, Any, Any, Any]:
    kwargs.setdefault("model", ANTHROPIC_MODEL)
    return make_interaction(provider="anthropic", **kwargs)


def _event(type_: str, **kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(type=type_, **kwargs)


def _thinking_tool_stream() -> list[SimpleNamespace]:
    """A stream that thinks, signs, answers, then calls a tool."""
    return [
        _event(
            "message_start",
            message=SimpleNamespace(id="msg_1", usage=SimpleNamespace(input_tokens=12)),
        ),
        _event(
            "content_block_start",
            index=0,
            content_block=SimpleNamespace(type="thinking"),
        ),
        _event(
            "content_block_delta",
            index=0,
            delta=SimpleNamespace(type="thinking_delta", thinking="Let me "),
        ),
        _event(
            "content_block_delta",
            index=0,
            delta=SimpleNamespace(type="thinking_delta", thinking="think."),
        ),
        _event(
            "content_block_delta",
            index=0,
            delta=SimpleNamespace(type="signature_delta", signature="sig-anthropic"),
        ),
        _event("content_block_stop", index=0),
        _event(
            "content_block_start", index=1, content_block=SimpleNamespace(type="text")
        ),
        _event(
            "content_block_delta",
            index=1,
            delta=SimpleNamespace(type="text_delta", text="The answer"),
        ),
        _event("content_block_stop", index=1),
        _event(
            "content_block_start",
            index=2,
            content_block=SimpleNamespace(
                type="tool_use", id="toolu_1", name="get_weather"
            ),
        ),
        _event(
            "content_block_delta",
            index=2,
            delta=SimpleNamespace(
                type="input_json_delta", partial_json='{"city":"NYC"}'
            ),
        ),
        _event("content_block_stop", index=2),
        _event(
            "message_delta",
            delta=SimpleNamespace(stop_reason="tool_use"),
            usage=SimpleNamespace(output_tokens=20),
        ),
        _event("message_stop"),
    ]


class _FakeStream:
    def __init__(
        self, events: list[SimpleNamespace], *, raise_exc: Exception | None = None
    ):
        self._events = events
        self._raise = raise_exc

    def __aiter__(self) -> _FakeStream:
        return self

    async def __anext__(self) -> SimpleNamespace:
        if self._raise is not None:
            raise self._raise
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


class _FakeMessages:
    def __init__(
        self, events: list[SimpleNamespace], *, raise_exc: Exception | None = None
    ):
        self._events = events
        self._raise = raise_exc
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> _FakeStream:
        self.last_kwargs = kwargs
        return _FakeStream(self._events, raise_exc=self._raise)


def _provider_with_stream(
    events: list[SimpleNamespace], *, raise_exc: Exception | None = None
) -> tuple[AnthropicProvider, _FakeMessages]:
    messages = _FakeMessages(events, raise_exc=raise_exc)
    provider = AnthropicProvider("test-key")
    provider._client = type("Client", (), {"messages": messages})()
    return provider, messages


@pytest.mark.asyncio
async def test_anthropic_stream_generate_reassembles_signed_thinking_blocks() -> None:
    """The terminal chunk carries the reconstructed signed thinking block."""
    provider, messages = _provider_with_stream(_thinking_tool_stream())

    chunks = [
        chunk async for chunk in provider.stream_generate(*_anthropic(content="Q"))
    ]

    assert messages.last_kwargs is not None
    assert messages.last_kwargs["stream"] is True

    state_chunks = [c for c in chunks if c.provider_state is not None]
    assert len(state_chunks) == 1
    assert state_chunks[0].provider_state == {
        "anthropic_thinking_blocks": [
            {
                "type": "thinking",
                "thinking": "Let me think.",
                "signature": "sig-anthropic",
            }
        ]
    }

    # total_tokens is computed from message_start input + message_delta output.
    final_usage = [c.usage for c in chunks if c.usage and "total_tokens" in c.usage]
    assert final_usage[-1]["total_tokens"] == 32


@pytest.mark.asyncio
async def test_anthropic_stream_through_interaction_assembles_output() -> None:
    """End to end: facets assemble and thinking blocks survive into continuation."""
    provider, _messages = _provider_with_stream(_thinking_tool_stream())
    config = Config(provider="anthropic", model=ANTHROPIC_MODEL, use_mock=True)
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

    types = [e.type for e in events]
    assert types[0] == "start"
    assert "reasoning_delta" in types
    assert "text_delta" in types
    assert "tool_call" in types
    assert types[-1] == "done"

    done = events[-1].output
    assert done is not None
    assert done.text == "The answer"
    assert done.reasoning == "Let me think."
    assert done.tool_calls[0].name == "get_weather"
    assert done.tool_calls[0].arguments == {"city": "NYC"}
    assert done.metrics.finish_reason == "tool_calls"

    # The signed thinking block must survive into the continuation for replay.
    assert done.continuation is not None
    serialized = json.dumps(done.continuation.to_jsonable())
    assert "sig-anthropic" in serialized


@pytest.mark.asyncio
async def test_anthropic_stream_error_raises_api_error() -> None:
    """A failure mid-stream surfaces as an APIError attributed to anthropic."""
    provider, _messages = _provider_with_stream([], raise_exc=RuntimeError("boom"))

    with pytest.raises(APIError) as exc:
        async for _chunk in provider.stream_generate(*_anthropic(content="Q")):
            pass

    assert exc.value.provider == "anthropic"
    assert exc.value.phase == "stream"
