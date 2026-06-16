"""OpenRouter streaming contract: SSE reuse and reasoning display."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from pollux.errors import APIError
from pollux.providers.openrouter import OpenRouterProvider
from tests.conftest import OPENROUTER_MODEL
from tests.helpers import make_interaction

pytestmark = pytest.mark.contract

_BASE_URL = "https://openrouter.ai/api/v1"


def _openrouter(**kwargs: Any) -> tuple[Any, Any, Any, Any]:
    kwargs.setdefault("model", OPENROUTER_MODEL)
    return make_interaction(provider="openrouter", **kwargs)


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj)}"


_TEXT_STREAM = [
    _sse({"id": "gen_1", "choices": [{"index": 0, "delta": {"role": "assistant"}}]}),
    _sse({"id": "gen_1", "choices": [{"index": 0, "delta": {"content": "Hel"}}]}),
    _sse(
        {"id": "gen_1", "choices": [{"index": 0, "delta": {"reasoning": "thinking"}}]}
    ),
    _sse({"id": "gen_1", "choices": [{"index": 0, "delta": {"content": "lo"}}]}),
    _sse(
        {"id": "gen_1", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    ),
    _sse(
        {
            "id": "gen_1",
            "choices": [],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
    ),
    "data: [DONE]",
]

_MODELS_PAYLOAD = {
    "data": [
        {
            "id": OPENROUTER_MODEL,
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["text"],
            },
            "supported_parameters": ["max_tokens", "temperature", "top_p"],
        }
    ]
}


class _FakeStreamResponse:
    def __init__(self, lines: list[str], status_code: int, error_body: Any) -> None:
        self._lines = lines
        self.status_code = status_code
        self.is_error = status_code >= 400
        self.request = httpx.Request("POST", f"{_BASE_URL}/chat/completions")
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


class _FakeOpenRouterStreamClient:
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

    async def get(self, path: str) -> Any:
        request = httpx.Request("GET", f"{_BASE_URL}{path}")
        return httpx.Response(200, json=_MODELS_PAYLOAD, request=request)

    def stream(self, method: str, path: str, *, json: dict[str, Any]) -> _FakeStreamCM:
        del method, path
        self.last_json = json
        return _FakeStreamCM(
            _FakeStreamResponse(self._lines, self._status_code, self._error_body)
        )

    async def aclose(self) -> None:
        return None


def _make_provider(client: _FakeOpenRouterStreamClient) -> OpenRouterProvider:
    provider = OpenRouterProvider("test-key")
    provider._client = client
    return provider


@pytest.mark.asyncio
async def test_openrouter_stream_generate_parses_sse_and_reasoning() -> None:
    """OpenRouter streams reuse the shared SSE parser, incl. delta.reasoning."""
    fake = _FakeOpenRouterStreamClient()
    provider = _make_provider(fake)

    chunks = [
        chunk async for chunk in provider.stream_generate(*_openrouter(content="Hi"))
    ]

    assert fake.last_json is not None
    assert fake.last_json["stream"] is True
    assert fake.last_json["stream_options"] == {"include_usage": True}

    assert "".join(c.text for c in chunks) == "Hello"
    assert any(c.reasoning == "thinking" for c in chunks)
    assert any(c.finish_reason == "stop" for c in chunks)
    assert any(c.usage and c.usage.get("total_tokens") == 5 for c in chunks)


@pytest.mark.asyncio
async def test_openrouter_stream_http_error_raises_api_error() -> None:
    """A non-2xx stream response surfaces as an APIError attributed to openrouter."""
    fake = _FakeOpenRouterStreamClient(
        status_code=502,
        error_body={"error": {"message": "upstream is down"}},
    )
    provider = _make_provider(fake)

    with pytest.raises(APIError) as exc:
        async for _chunk in provider.stream_generate(*_openrouter(content="Hi")):
            pass

    assert exc.value.provider == "openrouter"
    assert exc.value.phase == "stream"
