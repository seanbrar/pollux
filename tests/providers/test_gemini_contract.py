"""Provider contract characterization tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from pollux.errors import APIError, ConfigurationError
from pollux.providers.gemini import GeminiProvider
from pollux.providers.models import (
    ProviderFileAsset,
)
from tests.conftest import (
    GEMINI_MODEL,
)
from tests.helpers import make_interaction

pytestmark = pytest.mark.contract


def _gemini(**kwargs: Any) -> tuple[Any, Any, Any, Any]:
    """Build the four primitives for a gemini-provider generate() call."""
    kwargs.setdefault("model", GEMINI_MODEL)
    return make_interaction(provider="gemini", **kwargs)


def _obj(**attrs: Any) -> Any:
    """Create a strict SDK-like object for parser tests."""
    return SimpleNamespace(**attrs)


# =============================================================================
# Gemini Response Parsing (Characterization)
# =============================================================================


def test_gemini_parse_response_extracts_text_and_usage() -> None:
    """Characterize extraction of text and usage from Gemini response."""
    provider = GeminiProvider("test-key")

    fake_usage = MagicMock()
    fake_usage.prompt_token_count = 10
    fake_usage.candidates_token_count = 25
    fake_usage.total_token_count = 35
    fake_usage.thoughts_token_count = None
    fake_usage.cached_content_token_count = None

    fake_response = MagicMock()
    fake_response.text = "The answer is 42."
    fake_response.parsed = None
    fake_response.usage_metadata = fake_usage

    result = provider._parse_response(fake_response)

    assert result.text == "The answer is 42."
    assert result.usage == {
        "input_tokens": 10,
        "output_tokens": 25,
        "total_tokens": 35,
    }
    assert result.structured is None  # None parsed = no structured key


def test_gemini_parse_response_extracts_structured_from_parsed() -> None:
    """Characterize structured output extraction when .parsed exists."""
    provider = GeminiProvider("test-key")

    fake_response = MagicMock(spec=["text", "parsed"])
    fake_response.text = '{"title": "Test", "score": 95}'
    fake_response.parsed = {"title": "Test", "score": 95}

    result = provider._parse_response(fake_response)

    assert result.text == '{"title": "Test", "score": 95}'
    assert result.structured == {"title": "Test", "score": 95}
    assert result.usage == {}  # No usage_metadata attr = empty dict


def test_gemini_parse_response_falls_back_to_json_parsing() -> None:
    """Characterize JSON fallback when .parsed is None but text is JSON."""
    provider = GeminiProvider("test-key")

    fake_response = MagicMock()
    fake_response.text = '{"key": "value"}'
    fake_response.parsed = None
    fake_response.usage_metadata = None

    result = provider._parse_response(fake_response)

    assert result.text == '{"key": "value"}'
    assert result.structured == {"key": "value"}


def test_gemini_parse_response_handles_non_json_text() -> None:
    """Characterize behavior when text is not JSON and .parsed is None."""
    provider = GeminiProvider("test-key")

    fake_response = MagicMock()
    fake_response.text = "Just plain text, not JSON."
    fake_response.parsed = None
    fake_response.usage_metadata = None

    result = provider._parse_response(fake_response)

    assert result.text == "Just plain text, not JSON."
    assert result.structured is None


def test_gemini_parse_response_handles_missing_attributes() -> None:
    """Characterize graceful handling of responses missing expected attrs."""
    provider = GeminiProvider("test-key")

    fake_response = MagicMock(spec=[])  # spec=[] means no attributes

    result = provider._parse_response(fake_response)

    assert result.text == ""
    assert result.usage == {}
    assert result.structured is None


def test_gemini_parse_response_extracts_reasoning_from_thought_parts() -> None:
    """Characterize extraction of thinking content from thought-flagged parts."""
    provider = GeminiProvider("test-key")

    thought_part = _obj(thought=True, text="Let me reason about this...")
    answer_part = _obj(thought=False, text="The answer is 42.")
    fake_response = _obj(
        text="The answer is 42.",
        parsed=None,
        usage_metadata=None,
        candidates=[
            _obj(content=_obj(parts=[thought_part, answer_part])),
        ],
    )

    result = provider._parse_response(fake_response)

    assert result.reasoning == "Let me reason about this..."
    assert result.text == "The answer is 42."


def test_gemini_parse_response_extracts_url_context_artifacts() -> None:
    """URL Context metadata should be preserved as provider artifacts."""
    provider = GeminiProvider("test-key")

    class UrlContextMetadata:
        def model_dump(self, **_kwargs: Any) -> dict[str, Any]:
            return {
                "url_metadata": [
                    {
                        "retrieved_url": "https://example.com",
                        "url_retrieval_status": "URL_RETRIEVAL_STATUS_SUCCESS",
                    }
                ]
            }

    metadata = UrlContextMetadata()
    fake_response = _obj(
        text="ok",
        parsed=None,
        usage_metadata=None,
        candidates=[_obj(url_context_metadata=metadata)],
    )

    result = provider._parse_response(fake_response)

    assert result.artifacts == {
        "url_context_metadata": {
            "url_metadata": [
                {
                    "retrieved_url": "https://example.com",
                    "url_retrieval_status": "URL_RETRIEVAL_STATUS_SUCCESS",
                }
            ]
        }
    }


def test_gemini_parse_response_joins_multiple_thought_parts() -> None:
    """Multiple thought parts should be joined with double newlines."""
    provider = GeminiProvider("test-key")

    thought_1 = _obj(thought=True, text="First, consider X.")
    thought_2 = _obj(thought=True, text="Then, consider Y.")
    answer = _obj(thought=False, text="Result.")
    fake_response = _obj(
        text="Result.",
        parsed=None,
        usage_metadata=None,
        candidates=[
            _obj(content=_obj(parts=[thought_1, thought_2, answer])),
        ],
    )

    result = provider._parse_response(fake_response)

    assert result.reasoning == "First, consider X.\n\nThen, consider Y."


def test_gemini_parse_response_extracts_reasoning_tokens() -> None:
    """Characterize reasoning token count extraction from usage metadata."""
    provider = GeminiProvider("test-key")

    fake_usage = MagicMock()
    fake_usage.prompt_token_count = 10
    fake_usage.candidates_token_count = 25
    fake_usage.total_token_count = 35
    fake_usage.thoughts_token_count = 512

    fake_response = MagicMock()
    fake_response.text = "ok"
    fake_response.parsed = None
    fake_response.usage_metadata = fake_usage

    result = provider._parse_response(fake_response)

    assert result.usage["reasoning_tokens"] == 512


def test_gemini_parse_response_extracts_cached_tokens() -> None:
    """Cached content token count should appear in usage when present."""
    provider = GeminiProvider("test-key")

    fake_usage = MagicMock()
    fake_usage.prompt_token_count = 10_000
    fake_usage.candidates_token_count = 25
    fake_usage.total_token_count = 10_025
    fake_usage.thoughts_token_count = None
    fake_usage.cached_content_token_count = 9_500

    fake_response = MagicMock()
    fake_response.text = "ok"
    fake_response.parsed = None
    fake_response.usage_metadata = fake_usage

    result = provider._parse_response(fake_response)

    assert result.usage["cached_tokens"] == 9_500
    assert result.usage["input_tokens"] == 10_000


def test_gemini_parse_response_omits_cached_tokens_when_absent() -> None:
    """No cached_content_token_count field should produce no cached_tokens key."""
    provider = GeminiProvider("test-key")

    fake_usage = MagicMock()
    fake_usage.prompt_token_count = 10
    fake_usage.candidates_token_count = 25
    fake_usage.total_token_count = 35
    fake_usage.thoughts_token_count = None
    fake_usage.cached_content_token_count = None

    fake_response = MagicMock()
    fake_response.text = "ok"
    fake_response.parsed = None
    fake_response.usage_metadata = fake_usage

    result = provider._parse_response(fake_response)

    assert "cached_tokens" not in result.usage


def test_gemini_parse_response_omits_reasoning_when_no_thought_parts() -> None:
    """No thought-flagged parts should produce no reasoning key."""
    provider = GeminiProvider("test-key")

    answer_part = _obj(thought=False, text="Just an answer.")
    fake_response = _obj(
        text="Just an answer.",
        parsed=None,
        usage_metadata=None,
        candidates=[_obj(content=_obj(parts=[answer_part]))],
    )

    result = provider._parse_response(fake_response)

    assert result.reasoning is None


def test_gemini_parse_response_extracts_finish_reason() -> None:
    """Characterize finish_reason extraction and normalization from Gemini."""
    provider = GeminiProvider("test-key")

    def _with_finish_reason(reason: Any) -> Any:
        fake_response = _obj(
            text="ok",
            parsed=None,
            usage_metadata=None,
            candidates=[_obj(content=_obj(parts=[]), finish_reason=reason)],
        )
        return provider._parse_response(fake_response)

    assert _with_finish_reason(_obj(value="STOP")).finish_reason == "stop"
    assert _with_finish_reason("MAX_TOKENS").finish_reason == "max_tokens"


# =============================================================================
# Gemini Generate Config (Characterization)
# =============================================================================


@pytest.mark.golden_test("../characterization/v1/gemini_generate_config.yaml")
@pytest.mark.asyncio
async def test_gemini_generate_characterizes_config_shape(golden: Any) -> None:
    """Characterize the config dict passed to generate_content."""
    captured: dict[str, Any] = {}

    async def fake_generate_content(*, model: str, contents: Any, config: Any) -> Any:
        captured["model"] = model
        captured["contents"] = contents
        captured["config"] = config
        return MagicMock(text="ok", parsed=None, usage_metadata=None)

    provider = GeminiProvider("test-key")
    fake_models = MagicMock()
    fake_models.generate_content = fake_generate_content
    fake_aio = MagicMock()
    fake_aio.models = fake_models
    provider._client = MagicMock()
    provider._client.aio = fake_aio

    await provider.generate(
        *_gemini(
            content="What is 2+2?",
            instructions="Be concise.",
            cache_name="cachedContents/abc123",
            response_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
            },
        )
    )

    assert captured["model"] == GEMINI_MODEL
    # The golden file expects enums to be strings, so dump using json mode
    config_dict = captured["config"].model_dump(mode="json", exclude_none=True)
    assert golden.out["config"] == config_dict


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

    await provider.generate(*_gemini(content="Hello"))

    assert captured["config"] is not None


@pytest.mark.asyncio
async def test_gemini_generate_passes_thinking_level_from_reasoning_effort() -> None:
    """reasoning_effort should map to ThinkingConfig with thinking_level."""
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

    await provider.generate(
        *_gemini(
            model="models/gemini-3-flash-preview",
            content="Think hard.",
            reasoning_effort="low",
        )
    )

    config = captured["config"]
    assert config is not None
    tc = config.thinking_config
    assert tc.include_thoughts is True
    assert tc.thinking_level.value == "LOW"


@pytest.mark.asyncio
async def test_gemini_generate_passes_thinking_budget_from_reasoning_budget_tokens() -> (
    None
):
    """reasoning_budget_tokens should map to ThinkingConfig with thinking_budget."""
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

    await provider.generate(
        *_gemini(
            model="models/gemini-2.5-flash",
            content="Think less.",
            reasoning_budget_tokens=0,
        )
    )

    config = captured["config"]
    assert config is not None
    tc = config.thinking_config
    assert tc.include_thoughts is False
    assert tc.thinking_budget == 0


@pytest.mark.asyncio
async def test_gemini_generate_includes_thoughts_for_non_zero_budget() -> None:
    """A positive reasoning_budget_tokens should still request thought text."""
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

    await provider.generate(
        *_gemini(
            model="models/gemini-2.5-flash",
            content="Think a little.",
            reasoning_budget_tokens=512,
        )
    )

    config = captured["config"]
    assert config is not None
    tc = config.thinking_config
    assert tc.include_thoughts is True
    assert tc.thinking_budget == 512


@pytest.mark.asyncio
async def test_gemini_generate_attaches_video_metadata_from_source_settings() -> None:
    """Gemini adapter should interpret Pollux's explicit Gemini video settings."""
    captured: dict[str, Any] = {}

    async def fake_generate_content(**kwargs: Any) -> Any:
        captured["contents"] = kwargs.get("contents")
        return MagicMock(text="ok", parsed=None, usage_metadata=None)

    provider = GeminiProvider("test-key")
    fake_models = MagicMock()
    fake_models.generate_content = fake_generate_content
    fake_aio = MagicMock()
    fake_aio.models = fake_models
    provider._client = MagicMock()
    provider._client.aio = fake_aio

    await provider.generate(
        *_gemini(
            prepared_parts=[
                {
                    "uri": "https://example.test/files/uploaded_video",
                    "mime_type": "video/mp4",
                    "provider_hints": {
                        "video_metadata": {
                            "start_offset": "40s",
                            "end_offset": "80s",
                            "fps": 1.0,
                        },
                    },
                },
            ],
            content="Describe this clip.",
        )
    )

    contents = captured["contents"]
    assert contents[0].file_data.file_uri == "https://example.test/files/uploaded_video"
    assert contents[0].video_metadata.start_offset == "40s"
    assert contents[0].video_metadata.end_offset == "80s"
    assert contents[0].video_metadata.fps == 1.0


@pytest.mark.asyncio
async def test_gemini_generate_uses_url_context_tool_for_url_context_sources() -> None:
    """Gemini URL Context sources should become URL text plus url_context tool."""
    captured: dict[str, Any] = {}

    async def fake_generate_content(**kwargs: Any) -> Any:
        captured["contents"] = kwargs.get("contents")
        captured["config"] = kwargs.get("config")
        return MagicMock(text="ok", parsed=None, usage_metadata=None)

    provider = GeminiProvider("test-key")
    fake_models = MagicMock()
    fake_models.generate_content = fake_generate_content
    fake_aio = MagicMock()
    fake_aio.models = fake_models
    provider._client = MagicMock()
    provider._client.aio = fake_aio

    await provider.generate(
        *_gemini(
            prepared_parts=[
                {
                    "uri": "https://example.com/page",
                    "mime_type": "text/html",
                    "provider_hints": {"url_context": {}},
                },
            ],
            content="Summarize this URL.",
            tools=[{"name": "save_summary", "parameters": {"type": "object"}}],
        )
    )

    assert captured["contents"] == [
        "https://example.com/page",
        "Summarize this URL.",
    ]
    config = captured["config"]
    assert len(config.tools) == 2
    assert config.tools[0].function_declarations[0].name == "save_summary"
    assert config.tools[1].url_context is not None


@pytest.mark.asyncio
async def test_gemini_provider_options_merge_and_overlap() -> None:
    """Raw Gemini options should merge unless they overlap managed config keys."""
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

    await provider.generate(
        *_gemini(
            content="Hello",
            provider_options={"gemini": {"seed": 123}},
        )
    )

    assert captured["config"].seed == 123

    with pytest.raises(ConfigurationError, match="overlap"):
        await provider.generate(
            *_gemini(
                content="Hello",
                temperature=0.2,
                provider_options={"gemini": {"temperature": 0.7}},
            )
        )


@pytest.mark.asyncio
async def test_gemini_strips_additional_properties_from_tool_schemas() -> None:
    """Gemini rejects additionalProperties; Pollux should strip it."""
    captured: dict[str, Any] = {}

    async def fake_generate_content(
        *,
        model: str,  # noqa: ARG001
        contents: Any,  # noqa: ARG001
        config: Any,
    ) -> Any:
        captured["config"] = config
        return MagicMock(text="ok", parsed=None, usage_metadata=None)

    provider = GeminiProvider("test-key")
    fake_models = MagicMock()
    fake_models.generate_content = fake_generate_content
    fake_aio = MagicMock()
    fake_aio.models = fake_models
    provider._client = MagicMock()
    provider._client.aio = fake_aio

    await provider.generate(
        *_gemini(
            content="Pick a color",
            tools=[
                {
                    "name": "pick_color",
                    "description": "Pick a color.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "color": {"type": "string", "enum": ["red", "blue"]},
                        },
                        "required": ["color"],
                        "additionalProperties": False,
                    },
                }
            ],
            tool_choice="required",
        )
    )

    config = captured["config"]
    tool_decls = config.tools[0].function_declarations
    assert len(tool_decls) == 1
    params = tool_decls[0].parameters.model_dump(exclude_none=True)
    assert "additional_properties" not in params
    # Other fields should be preserved
    assert "properties" in params
    assert params["required"] == ["color"]


# =============================================================================
# Gemini Upload Behavior (Characterization)
# =============================================================================


def _fake_gemini_file(
    *,
    name: str = "files/abc123",
    uri: str | None = "https://generativelanguage.googleapis.com/v1beta/files/abc123",
    state: str = "ACTIVE",
    error_message: str | None = None,
) -> Any:
    """Create a minimal Gemini file object shape for upload tests."""
    state_obj = type("State", (), {"name": state})()
    error_obj = (
        None
        if error_message is None
        else type("FileError", (), {"message": error_message})()
    )
    return type(
        "GeminiFile",
        (),
        {"name": name, "uri": uri, "state": state_obj, "error": error_obj},
    )()


class _FakeGeminiFiles:
    """Captures upload/get interactions for Gemini file readiness polling."""

    def __init__(self, *, upload_result: Any, get_results: list[Any] | None) -> None:
        self.upload_result = upload_result
        self.get_results = list(get_results or [])
        self.upload_calls = 0
        self.get_calls = 0
        self.last_upload_kwargs: dict[str, Any] | None = None
        self.last_get_name: str | None = None

    async def upload(self, **kwargs: Any) -> Any:
        self.upload_calls += 1
        self.last_upload_kwargs = kwargs
        return self.upload_result

    async def get(self, *, name: str, config: Any = None) -> Any:  # noqa: ARG002
        self.get_calls += 1
        self.last_get_name = name
        if self.get_results:
            return self.get_results.pop(0)
        return self.upload_result


def _gemini_provider_with_files(files: Any) -> GeminiProvider:
    """Create a Gemini provider wired to fake aio.files methods."""
    provider = GeminiProvider("test-key")
    provider._client = type(
        "Client",
        (),
        {"aio": type("Aio", (), {"files": files})()},
    )()
    return provider


@pytest.mark.asyncio
async def test_gemini_upload_returns_active_without_polling(tmp_path: Any) -> None:
    """ACTIVE uploads should be returned immediately without files.get polling."""
    upload_result = _fake_gemini_file(state="ACTIVE")
    files = _FakeGeminiFiles(upload_result=upload_result, get_results=None)
    provider = _gemini_provider_with_files(files)

    asset = await provider.upload_file(
        path=tmp_path / "already-ready.pdf", mime_type="application/pdf"
    )

    assert isinstance(asset, ProviderFileAsset)
    assert asset.file_id == str(upload_result.uri)
    assert asset.provider == "gemini"
    assert asset.mime_type == "application/pdf"
    assert asset.is_inline_fallback is False
    assert files.upload_calls == 1
    assert files.get_calls == 0


@pytest.mark.asyncio
async def test_gemini_upload_polls_until_active_for_any_mime_type(
    tmp_path: Any,
) -> None:
    """PROCESSING uploads should poll by state, even for non-media MIME types."""
    processing = _fake_gemini_file(uri=None, state="PROCESSING")
    active = _fake_gemini_file(
        uri="https://generativelanguage.googleapis.com/v1beta/files/ready"
    )
    files = _FakeGeminiFiles(upload_result=processing, get_results=[active])
    provider = _gemini_provider_with_files(files)

    asset = await provider.upload_file(
        path=tmp_path / "still-processing.bin", mime_type="application/octet-stream"
    )

    assert isinstance(asset, ProviderFileAsset)
    assert (
        asset.file_id == "https://generativelanguage.googleapis.com/v1beta/files/ready"
    )
    assert asset.provider == "gemini"
    assert asset.mime_type == "application/octet-stream"
    assert asset.is_inline_fallback is False
    assert files.upload_calls == 1
    assert files.get_calls == 1
    assert files.last_get_name == "files/abc123"


@pytest.mark.asyncio
async def test_gemini_upload_raises_on_failed_processing(tmp_path: Any) -> None:
    """FAILED uploads should surface processing errors as APIError."""
    failed = _fake_gemini_file(state="FAILED", error_message="Virus scan failed")
    files = _FakeGeminiFiles(upload_result=failed, get_results=None)
    provider = _gemini_provider_with_files(files)

    with pytest.raises(APIError, match="Virus scan failed"):
        await provider.upload_file(
            path=tmp_path / "bad.bin",
            mime_type="application/pdf",
        )

    assert files.upload_calls == 1
    assert files.get_calls == 0


@pytest.mark.asyncio
async def test_gemini_create_cache_attaches_video_metadata_from_source_settings() -> (
    None
):
    """Gemini cache creation should interpret explicit Gemini video settings."""
    captured: dict[str, Any] = {}

    async def fake_create(*, model: str, config: Any) -> Any:
        captured["model"] = model
        captured["config"] = config
        return type("CacheResult", (), {"name": "cachedContents/video"})()

    provider = GeminiProvider("test-key")
    fake_caches = MagicMock()
    fake_caches.create = fake_create
    fake_aio = MagicMock()
    fake_aio.caches = fake_caches
    provider._client = MagicMock()
    provider._client.aio = fake_aio

    await provider.create_cache(
        model=GEMINI_MODEL,
        parts=[
            {
                "uri": "https://www.youtube.com/watch?v=9hE5-98ZeCg",
                "mime_type": "video/mp4",
                "provider_hints": {
                    "video_metadata": {
                        "start_offset": "40s",
                        "end_offset": "80s",
                        "fps": 1.0,
                    },
                },
            }
        ],
    )

    assert captured["model"] == GEMINI_MODEL
    contents = captured["config"].contents
    assert len(contents) == 1
    assert (
        contents[0].file_data.file_uri == "https://www.youtube.com/watch?v=9hE5-98ZeCg"
    )
    assert contents[0].video_metadata.start_offset == "40s"
    assert contents[0].video_metadata.end_offset == "80s"
    assert contents[0].video_metadata.fps == 1.0


# =============================================================================
# Response Parsing — Tool Call Extraction (Characterization)
# =============================================================================


def test_gemini_parse_response_extracts_tool_calls() -> None:
    """Characterize function_call → ToolCall extraction from Gemini response."""
    provider = GeminiProvider("test-key")

    fc = MagicMock()
    fc.id = "call_abc"
    fc.name = "get_weather"
    fc.args = {"city": "NYC"}

    fake_response = MagicMock()
    fake_response.text = ""
    fake_response.parsed = None
    fake_response.usage_metadata = None
    fake_response.function_calls = [fc]

    result = provider._parse_response(fake_response)

    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_abc"
    assert result.tool_calls[0].name == "get_weather"
    assert result.tool_calls[0].arguments == '{"city": "NYC"}'


def test_gemini_parse_response_generates_id_when_missing() -> None:
    """Gemini may omit fc.id; a stable synthetic ID should be generated."""
    provider = GeminiProvider("test-key")

    fc = MagicMock()
    fc.id = None
    fc.name = "do_thing"
    fc.args = {}

    fake_response = MagicMock()
    fake_response.text = ""
    fake_response.parsed = None
    fake_response.usage_metadata = None
    fake_response.function_calls = [fc]

    result = provider._parse_response(fake_response)

    assert result.tool_calls is not None
    assert result.tool_calls[0].id.startswith("call_")
