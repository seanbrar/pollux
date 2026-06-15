"""Provider contract characterization tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from pollux.errors import APIError, ConfigurationError
from pollux.interaction.continuation import Continuation, Message
from pollux.interaction.tools import ToolCall, ToolResult
from pollux.providers.openrouter import (
    OpenRouterProvider,
    _extract_error_message,
    _parse_response,
)
from tests.conftest import (
    OPENROUTER_MODEL,
)
from tests.helpers import make_interaction


def _openrouter(**kwargs: Any) -> tuple[Any, Any, Any, Any]:
    """Build the four primitives for an openrouter-provider generate() call."""
    kwargs.setdefault("model", OPENROUTER_MODEL)
    return make_interaction(provider="openrouter", **kwargs)


pytestmark = pytest.mark.contract


# =============================================================================
# OpenRouter Request / Response Characterization
# =============================================================================


class _FakeOpenRouterClient:
    """Captures payloads passed to OpenRouter chat completions."""

    def __init__(
        self,
        *,
        payload: Any = None,
        models_payload: Any = None,
    ) -> None:
        self.last_json: dict[str, Any] | None = None
        self.get_calls = 0
        self.closed = False
        self._payload = payload or {
            "id": "gen_123",
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
        self._models_payload = models_payload or {
            "data": [
                {
                    "id": OPENROUTER_MODEL,
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": [
                        "max_tokens",
                        "temperature",
                        "top_p",
                    ],
                },
                {
                    "id": "openai/gpt-4.1-mini",
                    "architecture": {
                        "input_modalities": ["text", "image", "file"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": [
                        "max_tokens",
                        "response_format",
                        "structured_outputs",
                        "temperature",
                        "tool_choice",
                        "tools",
                        "top_p",
                    ],
                },
                {
                    "id": "meta-llama/llama-3.2-11b-vision-instruct",
                    "architecture": {
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": [
                        "max_tokens",
                        "temperature",
                        "top_p",
                    ],
                },
                {
                    "id": "google/gemma-3-4b-it",
                    "architecture": {
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": [
                        "max_tokens",
                        "temperature",
                        "top_p",
                    ],
                },
            ]
        }

    async def post(self, path: str, json: dict[str, Any]) -> Any:
        self.last_json = json
        request = httpx.Request("POST", f"https://openrouter.ai/api/v1{path}")
        return httpx.Response(200, json=self._payload, request=request)

    async def get(self, path: str) -> Any:
        self.get_calls += 1
        request = httpx.Request("GET", f"https://openrouter.ai/api/v1{path}")
        return httpx.Response(200, json=self._models_payload, request=request)

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_openrouter_generate_builds_text_and_history_messages() -> None:
    """OpenRouter should send OpenAI-style messages for text/history requests."""
    fake_client = _FakeOpenRouterClient()

    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    result = await provider.generate(
        *_openrouter(
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

    assert fake_client.last_json == {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "Earlier answer"},
            {
                "role": "user",
                "content": [{"type": "text", "text": "Current prompt"}],
            },
        ],
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 128,
    }
    assert result.text == "ok"
    assert result.finish_reason == "stop"
    assert result.response_id == "gen_123"
    assert result.usage == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }
    assert fake_client.get_calls == 1


@pytest.mark.asyncio
async def test_openrouter_generate_characterizes_image_and_pdf_request_shape(
    tmp_path: Any,
) -> None:
    """OpenRouter should encode the verified multimodal subset correctly."""
    fake_client = _FakeOpenRouterClient()
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"\xff\xd8\xff")
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.7")

    image_asset = await provider.upload_file(image_path, "image/jpeg")
    pdf_asset = await provider.upload_file(pdf_path, "application/pdf")

    await provider.generate(
        *_openrouter(
            model="openai/gpt-4.1-mini",
            prepared_parts=[
                {"uri": "https://example.com/photo.jpg", "mime_type": "image/jpeg"},
                {
                    "uri": "https://example.com/report.pdf",
                    "mime_type": "application/pdf",
                },
                image_asset,
                pdf_asset,
            ],
            content="Summarize these assets.",
        )
    )

    assert fake_client.last_json == {
        "model": "openai/gpt-4.1-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "https://example.com/photo.jpg"},
                    },
                    {
                        "type": "file",
                        "file": {
                            "filename": "report.pdf",
                            "file_data": "https://example.com/report.pdf",
                        },
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_asset.file_id},
                    },
                    {
                        "type": "file",
                        "file": {
                            "filename": "report.pdf",
                            "file_data": pdf_asset.file_id,
                        },
                    },
                    {"type": "text", "text": "Summarize these assets."},
                ],
            }
        ],
    }
    assert image_asset.file_id.startswith("data:image/jpeg;base64,")
    assert pdf_asset.file_id.startswith("data:application/pdf;base64,")
    assert pdf_asset.file_name == "report.pdf"


@pytest.mark.asyncio
async def test_openrouter_generate_characterizes_tool_history_and_schema_shape() -> (
    None
):
    """OpenRouter should replay tool turns and map structured outputs."""
    fake_client = _FakeOpenRouterClient()
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openrouter(
            model="openai/gpt-4.1-mini",
            continuation=Continuation(
                messages=(
                    Message(role="user", content="Need orbit code."),
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=(
                            ToolCall.from_text(
                                id="call_orbit",
                                name="get_secret",
                                arguments_text='{"topic":"orbit"}',
                            ),
                        ),
                    ),
                ),
                provider_state={
                    "history": [
                        None,
                        {
                            "openrouter_reasoning_details": [
                                {
                                    "type": "reasoning.text",
                                    "text": "Need the tool result before answering.",
                                }
                            ]
                        },
                        None,
                    ]
                },
            ),
            tool_results=[
                ToolResult(call_id="call_orbit", content='{"code":"K9-ORBIT"}')
            ],
            content="Use the tool result to answer.",
            tools=[
                {
                    "name": "get_secret",
                    "description": "Return a code for a topic.",
                    "parameters": {
                        "type": "object",
                        "properties": {"topic": {"type": "string"}},
                        "required": ["topic"],
                    },
                }
            ],
            tool_choice={"name": "get_secret"},
            response_schema={
                "type": "object",
                "properties": {"secret_code": {"type": "string"}},
                "required": ["secret_code"],
            },
        )
    )

    assert fake_client.last_json == {
        "model": "openai/gpt-4.1-mini",
        "messages": [
            {"role": "user", "content": "Need orbit code."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_orbit",
                        "type": "function",
                        "function": {
                            "name": "get_secret",
                            "arguments": '{"topic":"orbit"}',
                        },
                    }
                ],
                "reasoning_details": [
                    {
                        "type": "reasoning.text",
                        "text": "Need the tool result before answering.",
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_orbit",
                "content": '{"code":"K9-ORBIT"}',
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": "Use the tool result to answer."}],
            },
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_secret",
                    "description": "Return a code for a topic.",
                    "parameters": {
                        "type": "object",
                        "properties": {"topic": {"type": "string"}},
                        "required": ["topic"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
        "tool_choice": {
            "type": "function",
            "function": {"name": "get_secret"},
        },
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "pollux_structured_output",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"secret_code": {"type": "string"}},
                    "required": ["secret_code"],
                    "additionalProperties": False,
                },
            },
        },
    }


@pytest.mark.asyncio
async def test_openrouter_generate_maps_reasoning_effort_and_extracts_reasoning_output() -> (
    None
):
    """OpenRouter reasoning should use the documented request and response shape."""
    fake_client = _FakeOpenRouterClient(
        payload={
            "id": "gen_reasoning_123",
            "choices": [
                {
                    "message": {
                        "content": "OK",
                        "reasoning": "The model thought briefly.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 9,
                "completion_tokens": 3,
                "reasoning_tokens": 4,
                "total_tokens": 16,
            },
        },
        models_payload={
            "data": [
                {
                    "id": "openai/gpt-5-nano",
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                    "supported_parameters": [
                        "max_tokens",
                        "reasoning",
                        "temperature",
                        "top_p",
                    ],
                }
            ]
        },
    )
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    result = await provider.generate(
        *_openrouter(
            model="openai/gpt-5-nano",
            content="Reply with exactly OK.",
            reasoning_effort="medium",
        )
    )

    assert fake_client.last_json == {
        "model": "openai/gpt-5-nano",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Reply with exactly OK."}],
            }
        ],
        "reasoning": {"effort": "medium"},
    }
    assert result.text == "OK"
    assert result.reasoning == "The model thought briefly."
    assert result.provider_state == {
        "openrouter_reasoning": "The model thought briefly."
    }
    assert result.usage == {
        "input_tokens": 9,
        "output_tokens": 3,
        "reasoning_tokens": 4,
        "total_tokens": 16,
    }


@pytest.mark.asyncio
async def test_openrouter_generate_replays_reasoning_only_history() -> None:
    """Reasoning-only assistant turns should survive replay without details."""
    fake_client = _FakeOpenRouterClient()
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openrouter(
            model="openai/gpt-4.1-mini",
            content="Continue.",
            continuation=Continuation(
                messages=(
                    Message(role="user", content="Think first."),
                    Message(role="assistant", content=""),
                ),
                provider_state={
                    "history": [
                        None,
                        {"openrouter_reasoning": "The model thought briefly."},
                    ]
                },
            ),
        )
    )

    assert fake_client.last_json == {
        "model": "openai/gpt-4.1-mini",
        "messages": [
            {"role": "user", "content": "Think first."},
            {
                "role": "assistant",
                "content": "",
                "reasoning": "The model thought briefly.",
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": "Continue."}],
            },
        ],
    }


@pytest.mark.asyncio
async def test_openrouter_generate_rejects_tools_when_model_lacks_support() -> None:
    """Metadata should distinguish unsupported-by-model tool calls."""
    fake_client = _FakeOpenRouterClient()
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    with pytest.raises(ConfigurationError, match="does not support tool calling"):
        await provider.generate(
            *_openrouter(
                content="Hello",
                tools=[{"name": "get_weather"}],
            )
        )


@pytest.mark.asyncio
async def test_openrouter_generate_rejects_structured_outputs_when_model_lacks_support() -> (
    None
):
    """Metadata should reject schema mode on models without support."""
    fake_client = _FakeOpenRouterClient()
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    with pytest.raises(ConfigurationError, match="does not support structured outputs"):
        await provider.generate(
            *_openrouter(
                content="Hello",
                response_schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
            )
        )


@pytest.mark.asyncio
async def test_openrouter_parse_response_extracts_tool_calls_and_reasoning_state() -> (
    None
):
    """Tool calls and reasoning_details should survive parsing for continuation."""
    fake_client = _FakeOpenRouterClient(
        payload={
            "id": "gen_tool_123",
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_orbit",
                                "type": "function",
                                "function": {
                                    "name": "get_secret",
                                    "arguments": '{"topic":"orbit"}',
                                },
                            }
                        ],
                        "reasoning_details": [
                            {
                                "type": "reasoning.text",
                                "text": "Need the tool result before answering.",
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 11,
                "completion_tokens": 4,
                "total_tokens": 15,
            },
        }
    )
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    result = await provider.generate(
        *_openrouter(
            model="openai/gpt-4.1-mini",
            content="Need orbit code.",
            tools=[{"name": "get_secret"}],
        )
    )

    assert result.text == ""
    assert result.finish_reason == "tool_calls"
    assert result.tool_calls is not None
    assert result.tool_calls[0].id == "call_orbit"
    assert result.tool_calls[0].name == "get_secret"
    assert result.tool_calls[0].arguments == '{"topic":"orbit"}'
    assert result.provider_state == {
        "openrouter_reasoning_details": [
            {
                "type": "reasoning.text",
                "text": "Need the tool result before answering.",
            }
        ]
    }


def test_openrouter_parse_response_extracts_cached_tokens() -> None:
    """prompt_tokens_details.cached_tokens should appear as cached_tokens."""
    result = _parse_response(
        {
            "id": "gen_cached_1",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 5_000,
                "completion_tokens": 25,
                "total_tokens": 5_025,
                "prompt_tokens_details": {"cached_tokens": 4_800},
            },
        },
        response_schema=None,
    )

    assert result.usage["cached_tokens"] == 4_800
    assert result.usage["input_tokens"] == 5_000


def test_openrouter_parse_response_preserves_reasoning_and_details_for_replay() -> None:
    """Reasoning replay should keep both plaintext and structured details."""
    result = _parse_response(
        {
            "id": "gen_reasoning_456",
            "choices": [
                {
                    "message": {
                        "content": "OK",
                        "reasoning": "The model thought briefly.",
                        "reasoning_details": [
                            {
                                "type": "reasoning.text",
                                "text": "The model thought briefly.",
                            }
                        ],
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 5},
        },
        response_schema=None,
    )

    assert result.reasoning == "The model thought briefly."
    assert result.provider_state == {
        "openrouter_reasoning": "The model thought briefly.",
        "openrouter_reasoning_details": [
            {
                "type": "reasoning.text",
                "text": "The model thought briefly.",
            }
        ],
    }


@pytest.mark.asyncio
async def test_openrouter_parse_response_extracts_structured_output() -> None:
    """Structured responses should parse from JSON text when schema mode is enabled."""
    fake_client = _FakeOpenRouterClient(
        payload={
            "id": "gen_schema_123",
            "choices": [
                {
                    "message": {
                        "content": '{"secret_code":"K9-ORBIT"}',
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 5,
                "total_tokens": 17,
            },
        }
    )
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    result = await provider.generate(
        *_openrouter(
            model="openai/gpt-4.1-mini",
            content="Need orbit code.",
            response_schema={
                "type": "object",
                "properties": {"secret_code": {"type": "string"}},
                "required": ["secret_code"],
            },
        )
    )

    assert result.text == '{"secret_code":"K9-ORBIT"}'
    assert result.structured == {"secret_code": "K9-ORBIT"}


@pytest.mark.asyncio
async def test_openrouter_generate_rejects_tool_choice_when_model_lacks_support() -> (
    None
):
    """Metadata should validate tool_choice separately from tools."""
    fake_client = _FakeOpenRouterClient()
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    with pytest.raises(ConfigurationError, match="does not support tool choice"):
        await provider.generate(
            *_openrouter(
                content="Hello",
                tool_choice="required",
            )
        )


@pytest.mark.asyncio
async def test_openrouter_generate_rejects_image_inputs_when_model_lacks_support() -> (
    None
):
    """Metadata should reject image inputs for text-only OpenRouter models."""
    fake_client = _FakeOpenRouterClient()
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    with pytest.raises(ConfigurationError, match="does not support image input"):
        await provider.generate(
            *_openrouter(
                prepared_parts=[
                    {
                        "uri": "https://example.com/photo.jpg",
                        "mime_type": "image/jpeg",
                    }
                ],
                content="prompt",
            )
        )


@pytest.mark.asyncio
async def test_openrouter_generate_allows_pdf_inputs_when_openrouter_parses_them() -> (
    None
):
    """PDF inputs should bypass native file-modality metadata checks."""
    fake_client = _FakeOpenRouterClient()
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openrouter(
            model="google/gemma-3-4b-it",
            prepared_parts=[
                {
                    "uri": "https://example.com/report.pdf",
                    "mime_type": "application/pdf",
                }
            ],
            content="prompt",
        )
    )

    assert fake_client.last_json == {
        "model": "google/gemma-3-4b-it",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "file",
                        "file": {
                            "filename": "report.pdf",
                            "file_data": "https://example.com/report.pdf",
                        },
                    },
                    {
                        "type": "text",
                        "text": "prompt",
                    },
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_openrouter_generate_rejects_non_pdf_file_inputs() -> None:
    """OpenRouter PR 3 should keep the file subset to PDFs only."""
    fake_client = _FakeOpenRouterClient()
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    with pytest.raises(ConfigurationError, match="Unsupported OpenRouter input type"):
        await provider.generate(
            *_openrouter(
                model="openai/gpt-4.1-mini",
                prepared_parts=[
                    {
                        "uri": "https://example.com/data.csv",
                        "mime_type": "text/csv",
                    }
                ],
                content="prompt",
            )
        )


@pytest.mark.asyncio
async def test_openrouter_generate_attributes_non_object_payload_errors() -> None:
    """Malformed chat completions payloads should keep provider attribution."""
    fake_client = _FakeOpenRouterClient(payload=["not", "an", "object"])
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    with pytest.raises(APIError, match="non-object response") as exc:
        await provider.generate(*_openrouter(content="Hello"))

    err = exc.value
    assert err.provider == "openrouter"
    assert err.phase == "generate"


@pytest.mark.asyncio
async def test_openrouter_validate_request_rejects_unknown_model() -> None:
    """Unknown OpenRouter model slugs should fail before dispatch."""
    fake_client = _FakeOpenRouterClient(models_payload={"data": []})
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    with pytest.raises(ConfigurationError, match="model not found"):
        await provider.validate_request(
            *_openrouter(model="missing/model", content="Hello")
        )


@pytest.mark.asyncio
async def test_openrouter_validate_request_rejects_reasoning_budget_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsupported reasoning budgets should fail before metadata lookup."""
    provider = OpenRouterProvider("test-key")

    async def fail_metadata_lookup(_model: str) -> Any:
        raise AssertionError("metadata lookup should not run")

    monkeypatch.setattr(provider, "_get_model_metadata", fail_metadata_lookup)

    with pytest.raises(
        ConfigurationError, match="Provider does not support reasoning_budget_tokens"
    ):
        await provider.validate_request(
            *_openrouter(content="Hello", reasoning_budget_tokens=0)
        )


@pytest.mark.asyncio
async def test_openrouter_validate_request_reuses_cached_metadata() -> None:
    """Metadata lookup should be cached across validations within the TTL."""
    fake_client = _FakeOpenRouterClient()
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    await provider.validate_request(*_openrouter(content="prompt"))
    await provider.validate_request(*_openrouter(content="prompt"))

    assert fake_client.get_calls == 1


@pytest.mark.asyncio
async def test_openrouter_validate_request_attributes_non_object_metadata_errors() -> (
    None
):
    """Malformed models payloads should report the metadata phase clearly."""
    fake_client = _FakeOpenRouterClient(models_payload=["not", "an", "object"])
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    with pytest.raises(APIError, match="non-object response") as exc:
        await provider.validate_request(*_openrouter(content="Hello"))

    err = exc.value
    assert err.provider == "openrouter"
    assert err.phase == "metadata"


@pytest.mark.asyncio
async def test_openrouter_validate_request_attributes_invalid_metadata_errors() -> None:
    """A missing models `data` list should still attribute metadata failures."""
    fake_client = _FakeOpenRouterClient(models_payload={"data": {}})
    provider = OpenRouterProvider("test-key")
    provider._client = fake_client

    with pytest.raises(APIError, match="invalid payload") as exc:
        await provider.validate_request(*_openrouter(content="Hello"))

    err = exc.value
    assert err.provider == "openrouter"
    assert err.phase == "metadata"


def test_openrouter_extract_error_message_prefers_nested_provider_message() -> None:
    """Nested provider messages should replace OpenRouter's generic stub."""
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(
        400,
        json={
            "error": {
                "message": "Provider returned error",
                "metadata": {
                    "provider_name": "Azure",
                    "raw": (
                        '{"error":{"message":"The image data you provided does not '
                        'represent a valid image."}}'
                    ),
                },
            }
        },
        request=request,
    )

    assert (
        _extract_error_message(response)
        == "Azure: The image data you provided does not represent a valid image."
    )


def test_openrouter_extract_error_message_handles_nested_error_arrays() -> None:
    """Cloudflare-style nested `errors` arrays should still surface the root cause."""
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(
        400,
        json={
            "error": {
                "message": "Provider returned error",
                "metadata": {
                    "provider_name": "Cloudflare",
                    "raw": (
                        '{"errors":[{"message":"AiError: Bad input: unsupported '
                        'content array","code":5006}],"success":false}'
                    ),
                },
            }
        },
        request=request,
    )

    assert (
        _extract_error_message(response)
        == "Cloudflare: AiError: Bad input: unsupported content array"
    )


@pytest.mark.asyncio
async def test_openrouter_upload_rejects_non_image_non_pdf_files(tmp_path: Any) -> None:
    """Local uploads should stay constrained to the verified subset."""
    provider = OpenRouterProvider("test-key")
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="local mime type"):
        await provider.upload_file(csv_path, "text/csv")


@pytest.mark.asyncio
async def test_openrouter_upload_attributes_local_read_failures() -> None:
    """Local file read failures should carry provider + upload phase context."""
    provider = OpenRouterProvider("test-key")

    with pytest.raises(APIError, match="Failed to read file") as exc:
        await provider.upload_file(
            Path("/definitely/missing/file.pdf"), "application/pdf"
        )

    err = exc.value
    assert err.provider == "openrouter"
    assert err.phase == "upload"


@pytest.mark.asyncio
async def test_openrouter_cache_raises() -> None:
    """create_cache should raise APIError: not supported."""
    provider = OpenRouterProvider("test-key")

    with pytest.raises(APIError, match="does not support context caching") as exc:
        await provider.create_cache(model=OPENROUTER_MODEL, parts=["test"])

    err = exc.value
    assert err.provider == "openrouter"
    assert err.phase == "cache"


@pytest.mark.asyncio
async def test_openrouter_provider_configures_timeout() -> None:
    """The OpenRouter provider HTTP client must configure an explicit timeout."""
    provider = OpenRouterProvider("test-key")
    client = provider._get_client()

    assert isinstance(client.timeout, httpx.Timeout)
    assert client.timeout.connect == 300.0
    assert client.timeout.read == 300.0
    assert client.timeout.write == 300.0
    assert client.timeout.pool == 300.0

    await provider.aclose()
