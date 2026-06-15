"""Provider contract characterization tests."""

from __future__ import annotations

from typing import Any

import pytest

from pollux.errors import APIError, ConfigurationError
from pollux.interaction.continuation import Continuation, Message
from pollux.providers._utils import to_strict_schema
from pollux.providers.models import (
    ProviderFileAsset,
)
from pollux.providers.openai import OpenAIProvider
from tests.conftest import (
    OPENAI_MODEL,
)
from tests.helpers import make_interaction
from tests.providers.helpers import FakeResponses, async_return


def _openai(**kwargs: Any) -> tuple[Any, Any, Any, Any]:
    """Build the four primitives for an openai-provider generate() call."""
    kwargs.setdefault("model", OPENAI_MODEL)
    return make_interaction(provider="openai", **kwargs)


pytestmark = pytest.mark.contract


# =============================================================================
# OpenAI Schema Normalization
# =============================================================================


def test_openai_strict_schema_adds_required_and_additional_properties() -> None:
    """OpenAI strict mode requires 'required' and 'additionalProperties: false'."""
    raw = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "meta": {
                "type": "object",
                "properties": {"score": {"type": "integer"}},
            },
        },
    }

    strict = to_strict_schema(raw)

    # Top-level enforcement
    assert strict["required"] == ["title", "meta"]
    assert strict["additionalProperties"] is False

    # Nested object enforcement
    meta = strict["properties"]["meta"]
    assert meta["required"] == ["score"]
    assert meta["additionalProperties"] is False


def test_openai_strict_schema_preserves_explicit_required_fields() -> None:
    """Schema normalization should not overwrite caller-provided required fields."""
    raw = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "subtitle": {"type": "string"},
        },
        "required": ["title"],
    }

    strict = to_strict_schema(raw)

    assert strict["required"] == ["title"]
    assert strict["additionalProperties"] is False


@pytest.mark.asyncio
async def test_openai_normalizes_tool_parameters_for_strict_mode() -> None:
    """Tool parameters should be auto-normalized when strict is true (default)."""
    responses = FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openai(
            content="Pick a color",
            tools=[
                {
                    "name": "pick_color",
                    "description": "Pick a color.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "color": {"type": "string"},
                        },
                    },
                }
            ],
            tool_choice="required",
        )
    )

    assert responses.last_kwargs is not None
    tool = responses.last_kwargs["tools"][0]
    assert tool["strict"] is True
    # Parameters should have been normalized for strict mode
    params = tool["parameters"]
    assert params["additionalProperties"] is False
    assert params["required"] == ["color"]


@pytest.mark.asyncio
async def test_openai_skips_normalization_when_strict_is_false() -> None:
    """Tool parameters should not be normalized when strict is explicitly false."""
    responses = FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openai(
            content="Pick a color",
            tools=[
                {
                    "name": "pick_color",
                    "parameters": {
                        "type": "object",
                        "properties": {"color": {"type": "string"}},
                    },
                    "strict": False,
                }
            ],
        )
    )

    assert responses.last_kwargs is not None
    tool = responses.last_kwargs["tools"][0]
    assert tool["strict"] is False
    # Parameters should NOT have been normalized
    params = tool["parameters"]
    assert "additionalProperties" not in params
    assert "required" not in params


@pytest.mark.asyncio
async def test_openai_provider_options_merge_and_overlap() -> None:
    """Raw OpenAI options should merge unless they overlap managed fields."""
    responses = FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openai(
            content="Search if needed.",
            provider_options={"openai": {"tools": [{"type": "web_search_preview"}]}},
        )
    )

    assert responses.last_kwargs is not None
    assert responses.last_kwargs["tools"] == [{"type": "web_search_preview"}]

    with pytest.raises(ConfigurationError, match="overlap"):
        await provider.generate(
            *_openai(
                content="Search if needed.",
                tools=[{"name": "get_weather", "parameters": {"type": "object"}}],
                provider_options={
                    "openai": {"tools": [{"type": "web_search_preview"}]}
                },
            )
        )


# =============================================================================
# OpenAI Request Part Building (Characterization)
# =============================================================================


@pytest.mark.golden_test("../characterization/v1/openai_generate_multimodal.yaml")
@pytest.mark.asyncio
async def test_openai_generate_characterizes_multimodal_request_shape(
    golden: Any,
) -> None:
    """Characterize the Responses API input shape for text + PDF + image."""
    responses = FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openai(
            prepared_parts=[
                {
                    "uri": "https://example.com/report.pdf",
                    "mime_type": "application/pdf",
                },
                {"uri": "https://example.com/photo.jpg", "mime_type": "image/jpeg"},
                ProviderFileAsset(
                    file_id="file_abc123",
                    provider="openai",
                    mime_type="application/pdf",
                ),
                ProviderFileAsset(
                    file_id="SGVsbG8gV29ybGQ=",
                    provider="openai",
                    mime_type="text/plain",
                    is_inline_fallback=True,
                ),
            ],
            content="Summarize these assets.",
        )
    )

    assert responses.last_kwargs is not None
    assert golden.out["request"] == responses.last_kwargs


@pytest.mark.asyncio
async def test_openai_generate_forwards_conversation_and_instructions() -> None:
    """Conversation params should map to Responses API fields."""
    responses = FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openai(
            content="What did I just ask?",
            instructions="Be concise.",
            history=[Message(role="user", content="Say hello.")],
        )
    )

    assert responses.last_kwargs is not None
    assert responses.last_kwargs["instructions"] == "Be concise."
    assert responses.last_kwargs["input"][0]["role"] == "user"
    assert responses.last_kwargs["input"][0]["content"][0] == {
        "type": "input_text",
        "text": "Say hello.",
    }
    assert responses.last_kwargs["input"][1]["role"] == "user"

    await provider.generate(
        *_openai(
            content="And now?",
            continuation=Continuation(
                response_id="resp_123",
                messages=(Message(role="user", content="This should be skipped."),),
            ),
        )
    )

    assert responses.last_kwargs["previous_response_id"] == "resp_123"
    assert len(responses.last_kwargs["input"]) == 1
    assert responses.last_kwargs["input"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_openai_rejects_unsupported_remote_mime_type() -> None:
    """Remote URIs with unsupported mime types should fail clearly."""
    provider = OpenAIProvider("test-key")
    provider._client = type(
        "Client",
        (),
        {"responses": type("R", (), {"create": lambda *_a, **_k: None})()},
    )()

    with pytest.raises(APIError, match="Unsupported remote mime type"):
        await provider.generate(
            *_openai(
                prepared_parts=[
                    {"uri": "https://example.com/video.mp4", "mime_type": "video/mp4"}
                ],
                content="prompt",
            )
        )


@pytest.mark.asyncio
async def test_openai_accepts_remote_text_like_mime_types() -> None:
    """Remote text-like URIs should use input_file.file_url."""
    responses = FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openai(
            prepared_parts=[
                {"uri": "https://example.com/data.csv", "mime_type": "text/csv"},
                {
                    "uri": "https://example.com/notes.md",
                    "mime_type": "text/markdown",
                },
            ],
            content="prompt",
        )
    )

    assert responses.last_kwargs is not None
    content = responses.last_kwargs["input"][0]["content"]
    assert content == [
        {"type": "input_file", "file_url": "https://example.com/data.csv"},
        {"type": "input_file", "file_url": "https://example.com/notes.md"},
        {"type": "input_text", "text": "prompt"},
    ]


@pytest.mark.asyncio
async def test_openai_generate_forwards_reasoning_effort_and_summary() -> None:
    """reasoning_effort should map to reasoning dict with effort and summary."""
    responses = FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openai(
            content="Think about this.",
            reasoning_effort="high",
        )
    )

    assert responses.last_kwargs is not None
    assert responses.last_kwargs["reasoning"] == {
        "effort": "high",
        "summary": "auto",
    }


@pytest.mark.asyncio
async def test_openai_generate_rejects_reasoning_budget_tokens() -> None:
    """OpenAI adapter should fail fast on unsupported budget-based reasoning."""
    responses = FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    with pytest.raises(
        ConfigurationError, match="Provider does not support reasoning_budget_tokens"
    ):
        await provider.generate(
            *_openai(
                content="Think about this.",
                reasoning_budget_tokens=0,
            )
        )

    assert responses.last_kwargs is None


@pytest.mark.asyncio
async def test_openai_extracts_reasoning_summary_from_response() -> None:
    """Reasoning summary items should be extracted into payload['reasoning']."""
    summary_item = type(
        "SummaryText", (), {"type": "summary_text", "text": "The model considered..."}
    )()
    reasoning_item = type(
        "ReasoningItem", (), {"type": "reasoning", "summary": [summary_item]}
    )()
    message_item = type("MessageItem", (), {"type": "message"})()

    fake_response = type(
        "Response",
        (),
        {
            "output_text": "The answer.",
            "id": "resp_123",
            "usage": None,
            "output": [reasoning_item, message_item],
        },
    )()

    responses = FakeResponses()
    responses.create = lambda **_kw: async_return(fake_response)  # type: ignore[method-assign]
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"responses": responses})()

    result = await provider.generate(
        *_openai(content="Think.", reasoning_effort="medium")
    )

    assert result.reasoning == "The model considered..."
    assert result.text == "The answer."


def test_openai_parse_extracts_output_annotations_as_artifacts() -> None:
    """OpenAI output annotations should be preserved in diagnostics artifacts."""
    annotation = {"type": "file_citation", "file_id": "file_123", "index": 0}
    content = type(
        "OutputText",
        (),
        {"type": "output_text", "text": "cited answer", "annotations": [annotation]},
    )()
    message_item = type("MessageItem", (), {"type": "message", "content": [content]})()
    fake_response = type(
        "Response",
        (),
        {
            "output_text": "cited answer",
            "id": "resp_123",
            "usage": None,
            "output": [message_item],
            "status": "completed",
        },
    )()

    result = OpenAIProvider._parse_response(fake_response, response_schema=None)

    assert result.artifacts == {"annotations": [annotation]}


@pytest.mark.asyncio
async def test_openai_extracts_reasoning_tokens_from_usage() -> None:
    """Reasoning token count should appear in usage when present."""
    out_details = type("Details", (), {"reasoning_tokens": 1024})()
    usage_obj = type(
        "Usage",
        (),
        {
            "input_tokens": 50,
            "output_tokens": 200,
            "total_tokens": 250,
            "output_tokens_details": out_details,
        },
    )()

    fake_response = type(
        "Response",
        (),
        {"output_text": "ok", "id": "resp_456", "usage": usage_obj, "output": []},
    )()

    responses = FakeResponses()
    responses.create = lambda **_kw: async_return(fake_response)  # type: ignore[method-assign]
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"responses": responses})()

    result = await provider.generate(*_openai(content="Test"))

    assert result.usage["reasoning_tokens"] == 1024
    assert result.usage["input_tokens"] == 50
    assert result.usage["output_tokens"] == 200


@pytest.mark.asyncio
async def test_openai_extracts_cached_tokens_from_usage() -> None:
    """Cached prompt token count should appear in usage when present."""
    in_details = type("InDetails", (), {"cached_tokens": 8_000})()
    usage_obj = type(
        "Usage",
        (),
        {
            "input_tokens": 10_000,
            "output_tokens": 200,
            "total_tokens": 10_200,
            "input_tokens_details": in_details,
        },
    )()

    fake_response = type(
        "Response",
        (),
        {"output_text": "ok", "id": "resp_789", "usage": usage_obj, "output": []},
    )()

    responses = FakeResponses()
    responses.create = lambda **_kw: async_return(fake_response)  # type: ignore[method-assign]
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"responses": responses})()

    result = await provider.generate(*_openai(content="Test"))

    assert result.usage["cached_tokens"] == 8_000
    assert result.usage["input_tokens"] == 10_000


# =============================================================================
# OpenAI Upload Behavior (Characterization)
# =============================================================================


class _FakeFiles:
    """Captures kwargs passed to files.create()."""

    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        return type("File", (), {"id": "file_abc123"})()


@pytest.mark.golden_test("../characterization/v1/openai_upload_*.yaml")
@pytest.mark.asyncio
async def test_openai_upload_characterization(golden: Any, tmp_path: Any) -> None:
    """Characterize OpenAI upload behavior (binary uses Files API; text inlines)."""
    case = golden["case"]
    expected = golden["expected"]

    mime_type = case["mime_type"]
    file_name = case["file_name"]
    file_path = tmp_path / file_name

    if "file_bytes" in case:
        file_path.write_bytes(case["file_bytes"].encode("utf-8"))
    else:
        file_path.write_text(case["file_text"])

    provider = OpenAIProvider("test-key")
    files = _FakeFiles()
    provider._client = type("Client", (), {"files": files})()

    asset = await provider.upload_file(path=file_path, mime_type=mime_type)

    assert isinstance(asset, ProviderFileAsset)

    expected_asset = expected.get("asset")
    if expected_asset:
        assert asset.file_id == expected_asset["file_id"]
        assert asset.provider == "openai"
        assert asset.mime_type == mime_type
        assert asset.is_inline_fallback == expected_asset.get(
            "is_inline_fallback", False
        )

    expected_files_create = expected.get("files_create")
    if expected_files_create is None:
        # Text inlines should not touch the Files API.
        assert files.last_kwargs is None
        return

    assert files.last_kwargs is not None
    # Don't characterize the local file object itself; only stable kwargs.
    normalized = {k: v for k, v in files.last_kwargs.items() if k != "file"}
    assert expected_files_create == normalized


# =============================================================================
# OpenAI Finish Reason (Characterization)
# =============================================================================


@pytest.mark.asyncio
async def test_openai_extracts_finish_reason() -> None:
    """Characterize status → finish_reason mapping for OpenAI Responses API."""
    cases = [
        ("completed", None, "completed"),
        ("incomplete", "max_output_tokens", "max_output_tokens"),
        ("incomplete", None, "incomplete"),
    ]
    for status, incomplete_reason, expected in cases:
        responses = FakeResponses(status=status, incomplete_reason=incomplete_reason)
        fake_client = type("Client", (), {"responses": responses})()

        provider = OpenAIProvider("test-key")
        provider._client = fake_client

        result = await provider.generate(*_openai(content="Hello"))

        assert result.finish_reason == expected, f"status={status}"


def test_openai_parse_response_extracts_tool_calls() -> None:
    """Characterize function_call output → ToolCall extraction from OpenAI response."""
    fc_item = type(
        "FunctionCall",
        (),
        {
            "type": "function_call",
            "call_id": "call_abc",
            "name": "get_weather",
            "arguments": '{"city": "NYC"}',
        },
    )()

    fake_response = type(
        "Response",
        (),
        {
            "output_text": "",
            "id": "resp_123",
            "usage": None,
            "output": [fc_item],
            "status": "completed",
            "incomplete_details": None,
        },
    )()

    result = OpenAIProvider._parse_response(fake_response, response_schema=None)

    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_abc"
    assert result.tool_calls[0].name == "get_weather"
    assert result.tool_calls[0].arguments == '{"city": "NYC"}'
