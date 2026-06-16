"""Provider contract characterization tests."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from pollux.errors import APIError, ConfigurationError
from pollux.interaction.continuation import Continuation, Message, build_continuation
from pollux.interaction.tools import ToolCall, ToolResult
from pollux.providers.local import LocalProvider
from tests.conftest import (
    LOCAL_MODEL,
)
from tests.helpers import make_interaction

pytestmark = pytest.mark.contract


def _local(**kwargs: Any) -> tuple[Any, Any, Any, Any]:
    """Build the four primitives for a local-provider generate() call."""
    return make_interaction(
        provider="local",
        base_url=_LOCAL_BASE_URL,
        model=LOCAL_MODEL,
        **kwargs,
    )


# =============================================================================
# Local Provider Request / Response Characterization
# =============================================================================


_LOCAL_BASE_URL = "http://localhost:11434/v1"


class _FakeLocalClient:
    """Captures payloads passed to a local OpenAI-compatible server."""

    def __init__(
        self,
        *,
        payload: Any = None,
        status_code: int = 200,
        error_body: Any = None,
    ) -> None:
        self.last_json: dict[str, Any] | None = None
        self.closed = False
        self._status_code = status_code
        self._error_body = error_body
        self._payload = payload or {
            "id": "chatcmpl_local_1",
            "choices": [
                {
                    "message": {"content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

    async def post(self, path: str, json: dict[str, Any]) -> Any:
        self.last_json = json
        request = httpx.Request("POST", f"{_LOCAL_BASE_URL}{path}")
        if self._status_code >= 400:
            return httpx.Response(
                self._status_code,
                json=self._error_body,
                request=request,
            )
        return httpx.Response(self._status_code, json=self._payload, request=request)

    async def aclose(self) -> None:
        self.closed = True


def _make_local_provider(client: _FakeLocalClient) -> LocalProvider:
    provider = LocalProvider(base_url=_LOCAL_BASE_URL)
    provider._client = client
    return provider


def test_local_capabilities_are_narrow() -> None:
    """Capabilities advertise only what the local provider actually supports."""
    caps = LocalProvider(base_url=_LOCAL_BASE_URL).capabilities

    assert caps.persistent_cache is False
    assert caps.uploads is False
    assert caps.structured_outputs is True
    assert caps.reasoning is False
    assert caps.reasoning_budget_tokens is False
    assert caps.deferred_delivery is False
    assert caps.conversation is True
    assert caps.implicit_caching is False


@pytest.mark.asyncio
async def test_local_generate_builds_chat_completions_payload() -> None:
    """Local should send system + history + user text as Chat Completions messages."""
    fake = _FakeLocalClient()
    provider = _make_local_provider(fake)

    result = await provider.generate(
        *_local(
            content="Current prompt",
            instructions="Be concise.",
            history=[
                Message(role="user", content="Earlier question"),
                Message(role="assistant", content="Earlier answer"),
            ],
            temperature=0.2,
            top_p=0.9,
            max_tokens=128,
        )
    )

    assert fake.last_json == {
        "model": LOCAL_MODEL,
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "Earlier answer"},
            {"role": "user", "content": "Current prompt"},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 128,
    }
    assert result.text == "ok"
    assert result.finish_reason == "stop"
    assert result.response_id == "chatcmpl_local_1"
    assert result.usage == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }


@pytest.mark.asyncio
async def test_local_generate_sets_json_mode_when_schema_present() -> None:
    """Response schemas should turn into response_format={"type": "json_schema"}."""
    fake = _FakeLocalClient(
        payload={
            "id": "chatcmpl_local_schema",
            "choices": [
                {
                    "message": {"content": '{"secret_code":"K9-ORBIT"}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 5},
        }
    )
    provider = _make_local_provider(fake)

    result = await provider.generate(
        *_local(
            content="Need orbit code.",
            response_schema={
                "type": "object",
                "properties": {"secret_code": {"type": "string"}},
                "required": ["secret_code"],
            },
        )
    )

    assert fake.last_json is not None
    assert fake.last_json["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "pollux_structured_output",
            "schema": {
                "type": "object",
                "properties": {"secret_code": {"type": "string"}},
                "required": ["secret_code"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }
    assert "tools" not in fake.last_json
    assert result.structured == {"secret_code": "K9-ORBIT"}


@pytest.mark.asyncio
async def test_local_generate_preserves_non_object_structured_json() -> None:
    """Structured output parsing should preserve valid non-object JSON values."""
    fake = _FakeLocalClient(
        payload={
            "id": "chatcmpl_local_schema_array",
            "choices": [
                {
                    "message": {"content": '["alpha","beta"]'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 5},
        }
    )
    provider = _make_local_provider(fake)

    result = await provider.generate(
        *_local(
            content="Need tags.",
            response_schema={
                "type": "array",
                "items": {"type": "string"},
            },
        )
    )

    assert result.structured == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_local_generate_extracts_reasoning_content() -> None:
    """reasoning_content should surface as reasoning in the ProviderResponse."""
    fake = _FakeLocalClient(
        payload={
            "id": "chatcmpl_local_reasoning",
            "choices": [
                {
                    "message": {
                        "content": "4",
                        "reasoning_content": "2+2=4",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 5},
        }
    )
    provider = _make_local_provider(fake)

    result = await provider.generate(
        *_local(
            content="2+2?",
        )
    )

    assert result.text == "4"
    assert result.reasoning == "2+2=4"


@pytest.mark.asyncio
async def test_local_reasoning_is_display_only_and_not_replayed() -> None:
    """Model reasoning surfaces on the output but never re-enters continuation.

    The local server returns reasoning out-of-band (``reasoning_content``);
    Pollux surfaces it as ``reasoning`` but must not echo it back into the replay
    messages an agent loop sends on the next turn.
    """
    reasoning_text = "INTERNAL-CHAIN-OF-THOUGHT: 2 + 2 = 4"
    first = _FakeLocalClient(
        payload={
            "id": "chatcmpl_reasoning_replay",
            "choices": [
                {
                    "message": {"content": "4", "reasoning_content": reasoning_text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 5},
        }
    )
    provider = _make_local_provider(first)

    snapshot, input_, requirements, config = _local(
        content="2+2?",
        history=[Message(role="user", content="Ready?")],
    )
    response = await provider.generate(snapshot, input_, requirements, config)
    assert response.reasoning == reasoning_text

    continuation = build_continuation(
        input_, response, user_content="2+2?", provider="local"
    )
    assert continuation is not None
    assistant = continuation.messages[-1]
    assert assistant.role == "assistant"
    assert assistant.content == "4"
    assert assistant.provider_state is None
    assert reasoning_text not in json.dumps(continuation.to_jsonable())

    # Replaying the continuation must not send reasoning back to the server.
    second = _FakeLocalClient()
    replay_provider = _make_local_provider(second)
    await replay_provider.generate(
        *_local(content="and 3+3?", continuation=continuation)
    )
    assert second.last_json is not None
    assert reasoning_text not in json.dumps(second.last_json)


@pytest.mark.asyncio
async def test_local_generate_returns_structured_none_when_response_is_not_json() -> (
    None
):
    """Non-JSON text despite JSON mode should surface as structured=None (not raise)."""
    fake = _FakeLocalClient(
        payload={
            "id": "chatcmpl_local_bad_json",
            "choices": [
                {
                    "message": {"content": "Sorry, I could not comply."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 4},
        }
    )
    provider = _make_local_provider(fake)

    result = await provider.generate(
        *_local(
            content="Need orbit code.",
            response_schema={
                "type": "object",
                "properties": {"secret_code": {"type": "string"}},
            },
        )
    )

    assert result.text == "Sorry, I could not comply."
    assert result.structured is None


@pytest.mark.asyncio
async def test_local_generate_extracts_cached_tokens() -> None:
    """prompt_tokens_details.cached_tokens should surface as cached_tokens."""
    fake = _FakeLocalClient(
        payload={
            "id": "chatcmpl_local_cached",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 5_000,
                "completion_tokens": 25,
                "total_tokens": 5_025,
                "prompt_tokens_details": {"cached_tokens": 4_800},
            },
        }
    )
    provider = _make_local_provider(fake)

    result = await provider.generate(
        *_local(content="hi"),
    )

    assert result.usage["cached_tokens"] == 4_800
    assert result.usage["input_tokens"] == 5_000


@pytest.mark.asyncio
async def test_local_generate_rejects_reasoning_effort() -> None:
    """Reasoning controls are unsupported even though reasoning output is parsed."""
    fake = _FakeLocalClient()
    provider = _make_local_provider(fake)

    with pytest.raises(ConfigurationError, match="reasoning_effort"):
        await provider.generate(
            *_local(
                content="hi",
                reasoning_effort="medium",
            )
        )

    assert fake.last_json is None


@pytest.mark.asyncio
async def test_local_generate_rejects_reasoning_budget_tokens() -> None:
    """Token-budget reasoning is explicitly unsupported on local."""
    provider = _make_local_provider(_FakeLocalClient())

    with pytest.raises(ConfigurationError, match="reasoning_budget_tokens"):
        await provider.generate(
            *_local(
                content="hi",
                reasoning_budget_tokens=1024,
            )
        )


@pytest.mark.asyncio
async def test_local_generate_sends_tools_and_tool_choice() -> None:
    """Tool declarations and tool_choice map to Chat Completions function shape."""
    fake = _FakeLocalClient()
    provider = _make_local_provider(fake)

    await provider.generate(
        *_local(
            content="What's the weather?",
            tools=[
                {
                    "name": "get_weather",
                    "description": "Look up the weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                }
            ],
            tool_choice={"name": "get_weather"},
        )
    )

    assert fake.last_json is not None
    assert fake.last_json["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Look up the weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "additionalProperties": False,
                    "required": ["city"],
                },
            },
        }
    ]
    assert fake.last_json["tool_choice"] == {
        "type": "function",
        "function": {"name": "get_weather"},
    }


@pytest.mark.asyncio
async def test_local_generate_replays_tool_history() -> None:
    """Assistant tool_calls and tool results replay as standard chat messages.

    Mirrors an agent loop: prior turns arrive as a continuation, and the tool
    result for the pending call arrives via ``tool_results`` (no new user text).
    """
    fake = _FakeLocalClient()
    provider = _make_local_provider(fake)

    await provider.generate(
        *_local(
            content="",
            continuation=Continuation(
                messages=(
                    Message(role="user", content="What's the weather in NYC?"),
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=(
                            ToolCall.from_text(
                                id="call_1",
                                name="get_weather",
                                arguments_text='{"city":"NYC"}',
                            ),
                        ),
                    ),
                ),
            ),
            tool_results=[ToolResult(call_id="call_1", content='{"temp":72}')],
        )
    )

    assert fake.last_json is not None
    assert fake.last_json["messages"] == [
        {"role": "user", "content": "What's the weather in NYC?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city":"NYC"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp":72}'},
    ]


@pytest.mark.asyncio
async def test_local_generate_parses_tool_calls() -> None:
    """tool_calls in the response surface on the ProviderResponse."""
    fake = _FakeLocalClient(
        payload={
            "id": "chatcmpl_local_tool",
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_xyz",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city":"NYC"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"total_tokens": 7},
        }
    )
    provider = _make_local_provider(fake)

    result = await provider.generate(*_local(content="Weather in NYC?"))

    assert result.finish_reason == "tool_calls"
    assert result.tool_calls is not None
    assert result.tool_calls[0].id == "call_xyz"
    assert result.tool_calls[0].name == "get_weather"
    assert result.tool_calls[0].arguments == '{"city":"NYC"}'


@pytest.mark.asyncio
async def test_local_generate_rejects_non_text_parts() -> None:
    """Multimodal / file parts are explicitly unsupported on local."""
    provider = _make_local_provider(_FakeLocalClient())

    with pytest.raises(ConfigurationError, match="file or multimodal input"):
        await provider.generate(
            *_local(
                content="Describe this image.",
                prepared_parts=[
                    {"uri": "https://example.com/photo.jpg", "mime_type": "image/jpeg"},
                ],
            )
        )


@pytest.mark.asyncio
async def test_local_upload_file_raises_api_error(tmp_path: Any) -> None:
    """Uploads are unsupported; should raise APIError, not silently noop."""
    provider = LocalProvider(base_url=_LOCAL_BASE_URL)
    text_path = tmp_path / "note.txt"
    text_path.write_text("hello", encoding="utf-8")

    with pytest.raises(APIError, match="does not support file uploads") as exc:
        await provider.upload_file(text_path, "text/plain")

    err = exc.value
    assert err.provider == "local"
    assert err.phase == "upload"


@pytest.mark.asyncio
async def test_local_create_cache_raises_api_error() -> None:
    """Persistent caches are unsupported; should raise APIError."""
    provider = LocalProvider(base_url=_LOCAL_BASE_URL)

    with pytest.raises(APIError, match="does not support context caching") as exc:
        await provider.create_cache(model=LOCAL_MODEL, parts=["test"])

    err = exc.value
    assert err.provider == "local"
    assert err.phase == "cache"


@pytest.mark.asyncio
async def test_local_generate_surfaces_http_error_as_api_error() -> None:
    """Non-2xx responses should turn into APIError attributed to 'local'."""
    fake = _FakeLocalClient(
        status_code=404,
        error_body={"error": {"message": f"model '{LOCAL_MODEL}' not found"}},
    )
    provider = _make_local_provider(fake)

    with pytest.raises(APIError) as exc:
        await provider.generate(
            *_local(content="hi"),
        )

    err = exc.value
    assert err.provider == "local"
    assert err.phase == "generate"
    assert err.status_code == 404
    assert err.hint is not None
    assert "Model not found" in err.hint


@pytest.mark.asyncio
async def test_local_aclose_closes_client() -> None:
    """aclose must close the underlying httpx client and be idempotent."""
    fake = _FakeLocalClient()
    provider = _make_local_provider(fake)

    await provider.aclose()
    assert fake.closed is True

    # Second call must not raise even after the client was cleared.
    await provider.aclose()


@pytest.mark.asyncio
async def test_local_provider_configures_timeout() -> None:
    """The local provider HTTP client must configure an explicit timeout."""
    provider = LocalProvider(base_url=_LOCAL_BASE_URL)
    client = provider._get_client()

    assert isinstance(client.timeout, httpx.Timeout)
    assert client.timeout.connect == 300.0
    assert client.timeout.read == 300.0

    await provider.aclose()
