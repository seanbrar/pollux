"""Local provider streaming contract: SSE parsing and end-to-end assembly."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from pollux import Environment, Input
from pollux.config import Config
from pollux.errors import APIError
from pollux.interaction.execute import stream_interaction
from pollux.interaction.requirements import OutputRequirements
from pollux.interaction.tools import ToolDeclaration
from pollux.providers.local import LocalProvider
from tests.conftest import LOCAL_MODEL
from tests.helpers import make_interaction

pytestmark = pytest.mark.contract

_LOCAL_BASE_URL = "http://localhost:11434/v1"


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj)}"


_TEXT_STREAM = [
    _sse({"id": "c1", "choices": [{"index": 0, "delta": {"role": "assistant"}}]}),
    _sse({"id": "c1", "choices": [{"index": 0, "delta": {"content": "Hel"}}]}),
    _sse({"id": "c1", "choices": [{"index": 0, "delta": {"content": "lo"}}]}),
    _sse({"id": "c1", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
    _sse(
        {
            "id": "c1",
            "choices": [],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
    ),
    "data: [DONE]",
]

_TOOL_STREAM = [
    _sse(
        {
            "id": "c2",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "get_weather", "arguments": ""},
                            }
                        ]
                    },
                }
            ],
        }
    ),
    _sse(
        {
            "id": "c2",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": '{"city":'}}
                        ]
                    },
                }
            ],
        }
    ),
    _sse(
        {
            "id": "c2",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": '"NYC"}'}}
                        ]
                    },
                }
            ],
        }
    ),
    _sse(
        {
            "id": "c2",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        }
    ),
    "data: [DONE]",
]


class _FakeStreamResponse:
    def __init__(self, lines: list[str], status_code: int, error_body: Any) -> None:
        self._lines = lines
        self.status_code = status_code
        self.is_error = status_code >= 400
        self.request = httpx.Request("POST", f"{_LOCAL_BASE_URL}/chat/completions")
        self._error_body = error_body
        self.text = json.dumps(error_body) if error_body is not None else ""

    async def aiter_lines(self) -> Any:
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return self.text.encode()

    def json(self) -> Any:
        return self._error_body


class _FakeStreamCM:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeStreamResponse:
        return self._response

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _FakeStreamClient:
    def __init__(
        self,
        lines: list[str] | None = None,
        *,
        status_code: int = 200,
        error_body: Any = None,
    ) -> None:
        self.last_json: dict[str, Any] | None = None
        self._lines = lines if lines is not None else _TEXT_STREAM
        self._status_code = status_code
        self._error_body = error_body
        self.closed = False

    def stream(self, method: str, path: str, *, json: dict[str, Any]) -> _FakeStreamCM:
        del method, path
        self.last_json = json
        return _FakeStreamCM(
            _FakeStreamResponse(self._lines, self._status_code, self._error_body)
        )

    async def aclose(self) -> None:
        self.closed = True


def _make_provider(client: _FakeStreamClient) -> LocalProvider:
    provider = LocalProvider(base_url=_LOCAL_BASE_URL)
    provider._client = client
    return provider


def _local(**kwargs: Any) -> tuple[Any, Any, Any, Any]:
    return make_interaction(
        provider="local", base_url=_LOCAL_BASE_URL, model=LOCAL_MODEL, **kwargs
    )


@pytest.mark.asyncio
async def test_local_stream_generate_parses_sse_chunks() -> None:
    """stream_generate sets stream flags and normalizes SSE into chunks."""
    fake = _FakeStreamClient()
    provider = _make_provider(fake)

    chunks = [chunk async for chunk in provider.stream_generate(*_local(content="Hi"))]

    assert fake.last_json is not None
    assert fake.last_json["stream"] is True
    assert fake.last_json["stream_options"] == {"include_usage": True}

    text = "".join(c.text for c in chunks)
    assert text == "Hello"
    assert any(c.finish_reason == "stop" for c in chunks)
    assert any(c.usage and c.usage.get("total_tokens") == 5 for c in chunks)
    assert any(c.response_id == "c1" for c in chunks)


@pytest.mark.asyncio
async def test_local_stream_assembles_tool_call_through_interaction() -> None:
    """Driven through stream_interaction, tool-call SSE assembles into Output."""
    fake = _FakeStreamClient(lines=_TOOL_STREAM)
    provider = _make_provider(fake)
    config = Config(provider="local", model=LOCAL_MODEL, base_url=_LOCAL_BASE_URL)
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
            environment,
            Input("Weather in NYC?"),
            OutputRequirements(),
            config,
            provider,
        )
    ]

    assert fake.last_json is not None
    assert fake.last_json["tools"][0]["function"]["name"] == "get_weather"

    completed = next(e for e in events if e.type == "tool_call")
    assert completed.tool_call is not None
    assert completed.tool_call.name == "get_weather"
    assert completed.tool_call.arguments == {"city": "NYC"}

    done = events[-1]
    assert done.type == "done"
    assert done.output is not None
    assert done.output.tool_calls[0].arguments == {"city": "NYC"}
    assert done.output.metrics.finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_local_stream_http_error_raises_api_error() -> None:
    """A non-2xx stream response surfaces as an APIError attributed to local."""
    fake = _FakeStreamClient(
        status_code=404,
        error_body={"error": {"message": f"model '{LOCAL_MODEL}' not found"}},
    )
    provider = _make_provider(fake)

    with pytest.raises(APIError) as exc:
        async for _chunk in provider.stream_generate(*_local(content="Hi")):
            pass

    err = exc.value
    assert err.provider == "local"
    assert err.phase == "stream"
    assert err.status_code == 404
