"""Gemini streaming contract: generate_content_stream mapping and assembly."""

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
from pollux.providers.gemini import GeminiProvider
from tests.conftest import GEMINI_MODEL
from tests.helpers import make_interaction

pytestmark = pytest.mark.contract


def _gemini(**kwargs: Any) -> tuple[Any, Any, Any, Any]:
    kwargs.setdefault("model", GEMINI_MODEL)
    return make_interaction(provider="gemini", **kwargs)


def _part(**kwargs: Any) -> SimpleNamespace:
    kwargs.setdefault("text", None)
    kwargs.setdefault("thought", False)
    kwargs.setdefault("function_call", None)
    return SimpleNamespace(**kwargs)


def _chunk(
    parts: list[SimpleNamespace], *, finish: Any = None, usage: Any = None
) -> SimpleNamespace:
    candidate = SimpleNamespace(
        content=SimpleNamespace(parts=parts), finish_reason=finish
    )
    return SimpleNamespace(candidates=[candidate], usage_metadata=usage)


def _thinking_tool_chunks() -> list[SimpleNamespace]:
    return [
        _chunk(
            [
                _part(text="thinking", thought=True),
                _part(text="Hello"),
            ]
        ),
        _chunk(
            [
                _part(
                    function_call=SimpleNamespace(
                        id=None, name="get_weather", args={"city": "NYC"}
                    )
                )
            ],
            finish="STOP",
            usage=SimpleNamespace(
                prompt_token_count=10,
                candidates_token_count=5,
                total_token_count=15,
                thoughts_token_count=2,
                cached_content_token_count=None,
            ),
        ),
    ]


class _AsyncChunks:
    def __init__(
        self, chunks: list[SimpleNamespace], raise_exc: Exception | None = None
    ):
        self._chunks = chunks
        self._raise = raise_exc

    def __aiter__(self) -> _AsyncChunks:
        return self

    async def __anext__(self) -> SimpleNamespace:
        if self._raise is not None:
            raise self._raise
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


def _provider_with(
    chunks: list[SimpleNamespace], raise_exc: Exception | None = None
) -> tuple[GeminiProvider, dict[str, Any]]:
    captured: dict[str, Any] = {}

    async def fake_stream(*, model: str, contents: Any, config: Any) -> _AsyncChunks:
        captured["model"] = model
        captured["contents"] = contents
        captured["config"] = config
        return _AsyncChunks(chunks, raise_exc=raise_exc)

    provider = GeminiProvider("test-key")
    provider._client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=fake_stream))
    )
    return provider, captured


@pytest.mark.asyncio
async def test_gemini_stream_through_interaction_assembles_output() -> None:
    """Streamed thought/text/function-call parts assemble into the Output."""
    provider, captured = _provider_with(_thinking_tool_chunks())
    config = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
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

    assert captured["model"] == GEMINI_MODEL

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
    assert done.usage.reasoning_tokens == 2
    assert done.metrics.finish_reason == "stop"


@pytest.mark.asyncio
async def test_gemini_stream_error_raises_api_error() -> None:
    """A failure mid-stream surfaces as an APIError attributed to gemini."""
    provider, _captured = _provider_with([], raise_exc=RuntimeError("boom"))

    with pytest.raises(APIError) as exc:
        async for _chunk in provider.stream_generate(*_gemini(content="Hi")):
            pass

    assert exc.value.provider == "gemini"
    assert exc.value.phase == "stream"
