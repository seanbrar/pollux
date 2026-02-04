"""Provider characterization tests.

These tests verify the internal request/response transformations for each
provider implementation. They use fake clients to characterize the exact
shapes sent to provider APIs without making real network calls.

Per MTMT: These are characterization tests that capture output format when
stability matters. Provider-specific API formats are consumed externally
and drift is hard to detect.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from pollux.errors import APIError
from pollux.providers.gemini import GeminiProvider
from pollux.providers.openai import OpenAIProvider, _to_openai_strict_schema

pytestmark = pytest.mark.unit


# =============================================================================
# Gemini Response Parsing (Characterization)
# =============================================================================


def test_gemini_parse_response_extracts_text_and_usage() -> None:
    """Characterize extraction of text and usage from Gemini response."""
    provider = GeminiProvider("test-key")

    # Simulate a typical Gemini SDK response object
    fake_usage = MagicMock()
    fake_usage.prompt_token_count = 10
    fake_usage.candidates_token_count = 25
    fake_usage.total_token_count = 35

    fake_response = MagicMock()
    fake_response.text = "The answer is 42."
    fake_response.parsed = None
    fake_response.usage_metadata = fake_usage

    result = provider._parse_response(fake_response)

    assert result["text"] == "The answer is 42."
    assert result["usage"] == {
        "prompt_token_count": 10,
        "candidates_token_count": 25,
        "total_token_count": 35,
    }
    assert "structured" not in result  # None parsed = no structured key


def test_gemini_parse_response_extracts_structured_from_parsed() -> None:
    """Characterize structured output extraction when .parsed exists."""
    provider = GeminiProvider("test-key")

    # Use spec to control which attributes exist
    fake_response = MagicMock(spec=["text", "parsed"])
    fake_response.text = '{"title": "Test", "score": 95}'
    fake_response.parsed = {"title": "Test", "score": 95}

    result = provider._parse_response(fake_response)

    assert result["text"] == '{"title": "Test", "score": 95}'
    assert result["structured"] == {"title": "Test", "score": 95}
    assert result["usage"] == {}  # No usage_metadata attr = empty dict


def test_gemini_parse_response_falls_back_to_json_parsing() -> None:
    """Characterize JSON fallback when .parsed is None but text is JSON."""
    provider = GeminiProvider("test-key")

    fake_response = MagicMock()
    fake_response.text = '{"key": "value"}'
    fake_response.parsed = None
    fake_response.usage_metadata = None

    result = provider._parse_response(fake_response)

    assert result["text"] == '{"key": "value"}'
    assert result["structured"] == {"key": "value"}


def test_gemini_parse_response_handles_non_json_text() -> None:
    """Characterize behavior when text is not JSON and .parsed is None."""
    provider = GeminiProvider("test-key")

    fake_response = MagicMock()
    fake_response.text = "Just plain text, not JSON."
    fake_response.parsed = None
    fake_response.usage_metadata = None

    result = provider._parse_response(fake_response)

    assert result["text"] == "Just plain text, not JSON."
    assert "structured" not in result


def test_gemini_parse_response_handles_missing_attributes() -> None:
    """Characterize graceful handling of responses missing expected attrs."""
    provider = GeminiProvider("test-key")

    # Minimal response with no .text attribute
    fake_response = MagicMock(spec=[])  # spec=[] means no attributes

    result = provider._parse_response(fake_response)

    assert result["text"] == ""
    assert result["usage"] == {}
    assert "structured" not in result


# =============================================================================
# Gemini Generate Config (Characterization)
# =============================================================================


@pytest.mark.asyncio
async def test_gemini_generate_characterizes_config_shape() -> None:
    """Characterize the config dict passed to generate_content."""
    captured: dict[str, Any] = {}

    async def fake_generate_content(*, model: str, contents: Any, config: Any) -> Any:
        captured["model"] = model
        captured["contents"] = contents
        captured["config"] = config
        # Return minimal response
        return MagicMock(text="ok", parsed=None, usage_metadata=None)

    # Create provider and inject fake client
    provider = GeminiProvider("test-key")
    fake_models = MagicMock()
    fake_models.generate_content = fake_generate_content
    fake_aio = MagicMock()
    fake_aio.models = fake_models
    provider._client = MagicMock()
    provider._client.aio = fake_aio

    await provider.generate(
        model="gemini-2.0-flash",
        parts=["What is 2+2?"],
        system_instruction="Be concise.",
        cache_name="cachedContents/abc123",
        response_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
        },
    )

    assert captured["model"] == "gemini-2.0-flash"
    assert captured["config"] == {
        "system_instruction": "Be concise.",
        "cached_content": "cachedContents/abc123",
        "response_mime_type": "application/json",
        "response_json_schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
        },
    }


@pytest.mark.asyncio
async def test_gemini_generate_omits_config_when_no_options() -> None:
    """Characterize that config is None when no special options provided."""
    captured: dict[str, Any] = {}

    async def fake_generate_content(**kwargs: Any) -> Any:
        captured["config"] = kwargs.get("config")
        return MagicMock(text="ok", parsed=None, usage_metadata=None)

    provider = GeminiProvider("test-key")
    fake_models = MagicMock()
    fake_models.generate_content = fake_generate_content
    fake_aio = MagicMock()
    fake_aio.models = fake_models
    provider._client = MagicMock()
    provider._client.aio = fake_aio

    await provider.generate(model="gemini-2.0-flash", parts=["Hello"])

    assert captured["config"] is None


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

    strict = _to_openai_strict_schema(raw)

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

    strict = _to_openai_strict_schema(raw)

    assert strict["required"] == ["title"]
    assert strict["additionalProperties"] is False


# =============================================================================
# OpenAI Request Part Building (Characterization)
# =============================================================================


class _FakeResponses:
    """Captures kwargs passed to responses.create()."""

    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        return type("Response", (), {"output_text": "ok", "usage": None})()


@pytest.mark.asyncio
async def test_openai_generate_characterizes_multimodal_request_shape() -> None:
    """Characterize the Responses API input shape for text + PDF + image."""
    responses = _FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        model="gpt-4o-mini",
        parts=[
            "Summarize these assets.",
            {"uri": "https://example.com/report.pdf", "mime_type": "application/pdf"},
            {"uri": "https://example.com/photo.jpg", "mime_type": "image/jpeg"},
            {"uri": "openai://file/file_abc123", "mime_type": "application/pdf"},
            {"uri": "openai://text/SGVsbG8gV29ybGQ=", "mime_type": "text/plain"},
        ],
    )

    assert responses.last_kwargs is not None
    user_content = responses.last_kwargs["input"][0]["content"]

    # Text prompt
    assert user_content[0] == {"type": "input_text", "text": "Summarize these assets."}

    # Remote URL assets
    assert user_content[1] == {
        "type": "input_file",
        "file_url": "https://example.com/report.pdf",
    }
    assert user_content[2] == {
        "type": "input_image",
        "image_url": "https://example.com/photo.jpg",
    }

    # Uploaded file (by file_id)
    assert user_content[3] == {"type": "input_file", "file_id": "file_abc123"}

    # Inline text (decoded from base64)
    assert user_content[4] == {"type": "input_text", "text": "Hello World"}


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
            model="gpt-4o-mini",
            parts=[{"uri": "https://example.com/video.mp4", "mime_type": "video/mp4"}],
        )


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


@pytest.mark.asyncio
async def test_openai_upload_binary_characterizes_files_api_call(
    tmp_path: Any,
) -> None:
    """Binary uploads should use Files API with user_data purpose and expiration."""
    files = _FakeFiles()
    fake_client = type("Client", (), {"files": files})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake pdf content")

    uri = await provider.upload_file(path=file_path, mime_type="application/pdf")

    assert uri == "openai://file/file_abc123"
    assert files.last_kwargs is not None
    assert files.last_kwargs["purpose"] == "user_data"
    assert files.last_kwargs["expires_after"] == {
        "anchor": "created_at",
        "seconds": 86_400,
    }


@pytest.mark.asyncio
async def test_openai_upload_text_inlines_as_base64_uri(tmp_path: Any) -> None:
    """Text files should bypass Files API and return inline base64 URIs."""
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": None})()  # Should not be called

    file_path = tmp_path / "doc.md"
    file_path.write_text("# Header\nBody text")

    uri = await provider.upload_file(path=file_path, mime_type="text/markdown")

    # Base64 of "# Header\nBody text"
    assert uri == "openai://text/IyBIZWFkZXIKQm9keSB0ZXh0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mime_type",
    ["application/json", "application/xml", "text/csv"],
)
async def test_openai_upload_text_like_types_inline(
    tmp_path: Any, mime_type: str
) -> None:
    """Common text-like types (JSON, XML, CSV) should inline like text."""
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": None})()

    file_path = tmp_path / "data.txt"
    file_path.write_text("content")

    uri = await provider.upload_file(path=file_path, mime_type=mime_type)

    assert uri.startswith("openai://text/")
