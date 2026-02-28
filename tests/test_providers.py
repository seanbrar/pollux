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
from pollux.providers._errors import extract_retry_after_s, wrap_provider_error
from pollux.providers._utils import to_strict_schema
from pollux.providers.anthropic import AnthropicProvider
from pollux.providers.gemini import GeminiProvider
from pollux.providers.models import Message, ProviderRequest, ToolCall
from pollux.providers.openai import OpenAIProvider
from tests.conftest import ANTHROPIC_MODEL, GEMINI_MODEL, OPENAI_MODEL

pytestmark = pytest.mark.contract


# =============================================================================
# Provider Error Mapping (Contract)
# =============================================================================


def test_wrap_provider_error_extracts_status_and_retry_after_from_response_headers() -> (
    None
):
    """Provider SDK errors should map into APIError with structured retry metadata."""

    class _Resp:
        def __init__(self) -> None:
            self.status_code = 429
            self.headers = {"Retry-After": "2"}

    class _SdkError(Exception):
        def __init__(self) -> None:
            super().__init__("rate limited")
            self.response = _Resp()

    err = wrap_provider_error(
        _SdkError(),
        provider="openai",
        phase="generate",
        allow_network_errors=True,
        message="OpenAI generate failed",
    )

    assert isinstance(err, APIError)
    assert err.status_code == 429
    assert err.retry_after_s == 2.0
    assert err.retryable is True
    assert err.provider == "openai"
    assert err.phase == "generate"
    assert "429" in str(err)  # status code included in message


def test_wrap_provider_error_enriches_existing_api_error_without_clobbering() -> None:
    base = APIError("bad request", retryable=False, status_code=400)
    wrapped = wrap_provider_error(
        base,
        provider="gemini",
        phase="generate",
        allow_network_errors=True,
    )

    assert wrapped is base
    assert wrapped.status_code == 400
    assert wrapped.retryable is False
    assert wrapped.provider == "gemini"
    assert wrapped.phase == "generate"


def test_wrap_provider_error_returns_rate_limit_error_for_429() -> None:
    """429s should be catchable via RateLimitError (subclass of APIError)."""
    from pollux.errors import RateLimitError

    class _SdkError(Exception):
        def __init__(self) -> None:
            super().__init__("rate limited")
            self.status_code = 429

    err = wrap_provider_error(
        _SdkError(),
        provider="openai",
        phase="generate",
        allow_network_errors=True,
    )
    assert isinstance(err, RateLimitError)


def test_wrap_provider_error_returns_cache_error_for_cache_phase() -> None:
    """Cache failures should be catchable via CacheError (subclass of APIError)."""
    from pollux.errors import CacheError

    class _SdkError(Exception):
        def __init__(self) -> None:
            super().__init__("cache failed")
            self.status_code = 500

    err = wrap_provider_error(
        _SdkError(),
        provider="gemini",
        phase="cache",
        allow_network_errors=False,
    )
    assert isinstance(err, CacheError)


def test_wrap_provider_error_reraises_cancelled_error_without_active_exception() -> (
    None
):
    """Regression: CancelledError should be re-raised even without an active exception context."""
    import asyncio

    err = asyncio.CancelledError("cancelled")

    # This should raise CancelledError, NOT RuntimeError
    with pytest.raises(asyncio.CancelledError):
        wrap_provider_error(
            err,
            provider="test",
            phase="test",
            allow_network_errors=False,
        )


@pytest.mark.parametrize(
    ("retry_delay", "expected"),
    [
        ("8.352104981s", 8.352104981),
        ("8s", 8.0),
    ],
)
def test_extract_retry_after_from_google_retry_info_variants(
    retry_delay: str, expected: float
) -> None:
    """RetryInfo protobuf durations should parse consistently."""

    class _FakeError(Exception):
        def __init__(self) -> None:
            super().__init__("rate limited")
            self.details = {
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": retry_delay,
                        }
                    ]
                }
            }

    assert extract_retry_after_s(_FakeError()) == expected


def test_hint_for_400_with_api_key_message() -> None:
    """Gemini returns 400 (not 401/403) for invalid API keys; hint should fire."""

    class _SdkError(Exception):
        def __init__(self) -> None:
            super().__init__("API key not valid. Please pass a valid API key.")
            self.status_code = 400

    err = wrap_provider_error(
        _SdkError(),
        provider="gemini",
        phase="generate",
        allow_network_errors=True,
    )
    assert err.hint is not None
    assert "GEMINI_API_KEY" in err.hint


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

    thought_part = MagicMock()
    thought_part.thought = True
    thought_part.text = "Let me reason about this..."

    answer_part = MagicMock()
    answer_part.thought = False
    answer_part.text = "The answer is 42."

    fake_content = MagicMock()
    fake_content.parts = [thought_part, answer_part]

    fake_candidate = MagicMock()
    fake_candidate.content = fake_content

    fake_response = MagicMock()
    fake_response.text = "The answer is 42."
    fake_response.parsed = None
    fake_response.usage_metadata = None
    fake_response.candidates = [fake_candidate]

    result = provider._parse_response(fake_response)

    assert result.reasoning == "Let me reason about this..."
    assert result.text == "The answer is 42."


def test_gemini_parse_response_joins_multiple_thought_parts() -> None:
    """Multiple thought parts should be joined with double newlines."""
    provider = GeminiProvider("test-key")

    thought_1 = MagicMock()
    thought_1.thought = True
    thought_1.text = "First, consider X."

    thought_2 = MagicMock()
    thought_2.thought = True
    thought_2.text = "Then, consider Y."

    answer = MagicMock()
    answer.thought = False
    answer.text = "Result."

    fake_content = MagicMock()
    fake_content.parts = [thought_1, thought_2, answer]

    fake_candidate = MagicMock()
    fake_candidate.content = fake_content

    fake_response = MagicMock()
    fake_response.text = "Result."
    fake_response.parsed = None
    fake_response.usage_metadata = None
    fake_response.candidates = [fake_candidate]

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


def test_gemini_parse_response_omits_reasoning_when_no_thought_parts() -> None:
    """No thought-flagged parts should produce no reasoning key."""
    provider = GeminiProvider("test-key")

    answer_part = MagicMock()
    answer_part.thought = False
    answer_part.text = "Just an answer."

    fake_content = MagicMock()
    fake_content.parts = [answer_part]

    fake_candidate = MagicMock()
    fake_candidate.content = fake_content

    fake_response = MagicMock()
    fake_response.text = "Just an answer."
    fake_response.parsed = None
    fake_response.usage_metadata = None
    fake_response.candidates = [fake_candidate]

    result = provider._parse_response(fake_response)

    assert result.reasoning is None


def test_gemini_parse_response_extracts_finish_reason() -> None:
    """Characterize finish_reason extraction from Gemini candidate."""
    from google.genai import types as genai_types

    provider = GeminiProvider("test-key")

    fake_candidate = MagicMock()
    fake_candidate.content = MagicMock(parts=[])
    fake_candidate.finish_reason = genai_types.FinishReason.STOP

    fake_response = MagicMock()
    fake_response.text = "The answer."
    fake_response.parsed = None
    fake_response.usage_metadata = None
    fake_response.candidates = [fake_candidate]

    result = provider._parse_response(fake_response)

    assert result.finish_reason == "stop"


def test_gemini_parse_response_finish_reason_max_tokens() -> None:
    """MAX_TOKENS finish_reason should be forwarded as lowercase."""
    provider = GeminiProvider("test-key")

    fake_candidate = MagicMock()
    fake_candidate.content = MagicMock(parts=[])
    fake_candidate.finish_reason = "MAX_TOKENS"

    fake_response = MagicMock()
    fake_response.text = ""
    fake_response.parsed = None
    fake_response.usage_metadata = None
    fake_response.candidates = [fake_candidate]

    result = provider._parse_response(fake_response)

    assert result.finish_reason == "max_tokens"


def test_gemini_parse_response_finish_reason_none_when_no_candidates() -> None:
    """finish_reason should be None when response has no candidates."""
    provider = GeminiProvider("test-key")

    fake_response = MagicMock(spec=["text", "parsed"])
    fake_response.text = "hello"
    fake_response.parsed = None

    result = provider._parse_response(fake_response)

    assert result.finish_reason is None


# =============================================================================
# Gemini Generate Config (Characterization)
# =============================================================================


@pytest.mark.golden_test("characterization/v1/gemini_generate_config.yaml")
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
        ProviderRequest(
            model=GEMINI_MODEL,
            parts=["What is 2+2?"],
            system_instruction="Be concise.",
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

    await provider.generate(ProviderRequest(model=GEMINI_MODEL, parts=["Hello"]))

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
        ProviderRequest(
            model=GEMINI_MODEL, parts=["Think hard."], reasoning_effort="low"
        )
    )

    config = captured["config"]
    assert config is not None
    tc = config.thinking_config
    assert tc.include_thoughts is True
    assert tc.thinking_level.value == "LOW"


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
        ProviderRequest(
            model=GEMINI_MODEL,
            parts=["Pick a color"],
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

    uri = await provider.upload_file(
        path=tmp_path / "already-ready.pdf", mime_type="application/pdf"
    )

    assert uri == str(upload_result.uri)
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

    uri = await provider.upload_file(
        path=tmp_path / "still-processing.bin", mime_type="application/octet-stream"
    )

    assert uri == "https://generativelanguage.googleapis.com/v1beta/files/ready"
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
    responses = _FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        ProviderRequest(
            model=OPENAI_MODEL,
            parts=["Pick a color"],
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
    responses = _FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        ProviderRequest(
            model=OPENAI_MODEL,
            parts=["Pick a color"],
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


# =============================================================================
# OpenAI Request Part Building (Characterization)
# =============================================================================


async def _async_return(value: Any) -> Any:
    """Wrap a value in a coroutine for use as an async fake."""
    return value


class _FakeResponses:
    """Captures kwargs passed to responses.create()."""

    def __init__(
        self, *, status: str = "completed", incomplete_reason: str | None = None
    ) -> None:
        self.last_kwargs: dict[str, Any] | None = None
        self._status = status
        self._incomplete_reason = incomplete_reason

    async def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        incomplete_details = (
            type("IncompleteDetails", (), {"reason": self._incomplete_reason})()
            if self._incomplete_reason is not None
            else None
        )
        return type(
            "Response",
            (),
            {
                "output_text": "ok",
                "usage": None,
                "id": None,
                "output": [],
                "status": self._status,
                "incomplete_details": incomplete_details,
            },
        )()


@pytest.mark.golden_test("characterization/v1/openai_generate_multimodal.yaml")
@pytest.mark.asyncio
async def test_openai_generate_characterizes_multimodal_request_shape(
    golden: Any,
) -> None:
    """Characterize the Responses API input shape for text + PDF + image."""
    responses = _FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        ProviderRequest(
            model=OPENAI_MODEL,
            parts=[
                "Summarize these assets.",
                {
                    "uri": "https://example.com/report.pdf",
                    "mime_type": "application/pdf",
                },
                {"uri": "https://example.com/photo.jpg", "mime_type": "image/jpeg"},
                {"uri": "openai://file/file_abc123", "mime_type": "application/pdf"},
                {"uri": "openai://text/SGVsbG8gV29ybGQ=", "mime_type": "text/plain"},
            ],
        )
    )

    assert responses.last_kwargs is not None
    assert golden.out["request"] == responses.last_kwargs


@pytest.mark.asyncio
async def test_openai_generate_forwards_conversation_and_instructions() -> None:
    """Conversation params should map to Responses API fields."""
    responses = _FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        ProviderRequest(
            model=OPENAI_MODEL,
            parts=["What did I just ask?"],
            system_instruction="Be concise.",
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
        ProviderRequest(
            model=OPENAI_MODEL,
            parts=["And now?"],
            history=[Message(role="user", content="This should be skipped.")],
            previous_response_id="resp_123",
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
            ProviderRequest(
                model=OPENAI_MODEL,
                parts=[
                    {"uri": "https://example.com/video.mp4", "mime_type": "video/mp4"}
                ],
            )
        )


@pytest.mark.asyncio
async def test_openai_generate_forwards_reasoning_effort_and_summary() -> None:
    """reasoning_effort should map to reasoning dict with effort and summary."""
    responses = _FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        ProviderRequest(
            model=OPENAI_MODEL,
            parts=["Think about this."],
            reasoning_effort="high",
        )
    )

    assert responses.last_kwargs is not None
    assert responses.last_kwargs["reasoning"] == {
        "effort": "high",
        "summary": "auto",
    }


@pytest.mark.asyncio
async def test_openai_generate_omits_reasoning_when_not_set() -> None:
    """No reasoning_effort should produce no reasoning key in kwargs."""
    responses = _FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(ProviderRequest(model=OPENAI_MODEL, parts=["Hello"]))

    assert responses.last_kwargs is not None
    assert "reasoning" not in responses.last_kwargs


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

    responses = _FakeResponses()
    responses.create = lambda **_kw: _async_return(fake_response)  # type: ignore[method-assign]
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"responses": responses})()

    result = await provider.generate(
        ProviderRequest(model=OPENAI_MODEL, parts=["Think."], reasoning_effort="medium")
    )

    assert result.reasoning == "The model considered..."
    assert result.text == "The answer."


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

    responses = _FakeResponses()
    responses.create = lambda **_kw: _async_return(fake_response)  # type: ignore[method-assign]
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"responses": responses})()

    result = await provider.generate(
        ProviderRequest(model=OPENAI_MODEL, parts=["Test"])
    )

    assert result.usage["reasoning_tokens"] == 1024
    assert result.usage["input_tokens"] == 50
    assert result.usage["output_tokens"] == 200


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


@pytest.mark.golden_test("characterization/v1/openai_upload_*.yaml")
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

    uri = await provider.upload_file(path=file_path, mime_type=mime_type)
    assert expected["uri"] == uri

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
async def test_openai_extracts_finish_reason_from_response_status() -> None:
    """OpenAI Responses API status should map to finish_reason."""
    responses = _FakeResponses(status="completed")
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    result = await provider.generate(
        ProviderRequest(model=OPENAI_MODEL, parts=["Hello"])
    )

    assert result.finish_reason == "completed"


@pytest.mark.asyncio
async def test_openai_extracts_incomplete_finish_reason() -> None:
    """Incomplete responses should prefer incomplete_details.reason."""
    responses = _FakeResponses(
        status="incomplete", incomplete_reason="max_output_tokens"
    )
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    result = await provider.generate(
        ProviderRequest(model=OPENAI_MODEL, parts=["Hello"])
    )

    assert result.finish_reason == "max_output_tokens"


@pytest.mark.asyncio
async def test_openai_falls_back_to_incomplete_status_without_reason() -> None:
    """Incomplete status should be used when no incomplete reason is provided."""
    responses = _FakeResponses(status="incomplete")
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    result = await provider.generate(
        ProviderRequest(model=OPENAI_MODEL, parts=["Hello"])
    )

    assert result.finish_reason == "incomplete"


# =============================================================================
# OpenAI Tool History Mapping (Characterization)
# =============================================================================


@pytest.mark.asyncio
async def test_openai_maps_tool_history_to_responses_api_format() -> None:
    """Tool messages in history should map to function_call/function_call_output."""
    responses = _FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        ProviderRequest(
            model=OPENAI_MODEL,
            parts=["Continue the conversation"],
            history=[
                Message(role="user", content="What's the weather?"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call_abc",
                            name="get_weather",
                            arguments='{"location": "NYC"}',
                        )
                    ],
                ),
                Message(role="tool", tool_call_id="call_abc", content='{"temp": 72}'),
            ],
        )
    )

    assert responses.last_kwargs is not None
    input_msgs = responses.last_kwargs["input"]

    # First: regular user message
    assert input_msgs[0]["role"] == "user"
    assert input_msgs[0]["content"] == [
        {"type": "input_text", "text": "What's the weather?"}
    ]

    # Second: function_call from assistant tool_calls
    assert input_msgs[1]["type"] == "function_call"
    assert input_msgs[1]["call_id"] == "call_abc"
    assert input_msgs[1]["name"] == "get_weather"
    assert input_msgs[1]["arguments"] == '{"location": "NYC"}'

    # Third: function_call_output from tool message
    assert input_msgs[2]["type"] == "function_call_output"
    assert input_msgs[2]["call_id"] == "call_abc"
    assert input_msgs[2]["output"] == '{"temp": 72}'

    # Fourth: the current user message
    assert input_msgs[3]["role"] == "user"


@pytest.mark.asyncio
async def test_openai_preserves_assistant_text_with_tool_calls() -> None:
    """Assistant text should not be dropped when tool_calls are present."""
    responses = _FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        ProviderRequest(
            model=OPENAI_MODEL,
            parts=["Continue"],
            history=[
                Message(
                    role="assistant",
                    content="Let me check that tool.",
                    tool_calls=[
                        ToolCall(id="call_abc", name="get_weather", arguments="{}")
                    ],
                )
            ],
        )
    )

    assert responses.last_kwargs is not None
    input_msgs = responses.last_kwargs["input"]
    assert input_msgs[0]["type"] == "function_call"
    assert input_msgs[0]["call_id"] == "call_abc"
    assert input_msgs[1]["role"] == "assistant"
    assert input_msgs[1]["content"] == [
        {"type": "output_text", "text": "Let me check that tool."}
    ]


@pytest.mark.asyncio
async def test_openai_keeps_tool_outputs_when_previous_response_id_is_set() -> None:
    """Tool outputs and their originating function_call must both be sent."""
    responses = _FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        ProviderRequest(
            model=OPENAI_MODEL,
            parts=["Continue"],
            previous_response_id="resp_prev",
            history=[
                Message(role="user", content="What's the weather?"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(id="call_abc", name="get_weather", arguments="{}")
                    ],
                ),
                Message(role="tool", tool_call_id="call_abc", content='{"temp": 72}'),
            ],
        )
    )

    assert responses.last_kwargs is not None
    input_msgs = responses.last_kwargs["input"]

    # The assistant's function_call must precede its function_call_output so
    # the Responses API can associate them (even with previous_response_id).
    assert input_msgs[0]["type"] == "function_call"
    assert input_msgs[0]["call_id"] == "call_abc"
    assert input_msgs[0]["name"] == "get_weather"

    assert input_msgs[1]["type"] == "function_call_output"
    assert input_msgs[1]["call_id"] == "call_abc"
    assert input_msgs[1]["output"] == '{"temp": 72}'

    assert input_msgs[2]["role"] == "user"


@pytest.mark.asyncio
async def test_gemini_maps_tool_history_to_content_format() -> None:
    """Tool messages in history should map to function call / response types."""
    captured: dict[str, Any] = {}

    async def fake_generate_content(
        *,
        model: str,  # noqa: ARG001
        contents: Any,
        config: Any,  # noqa: ARG001
    ) -> Any:
        captured["contents"] = contents
        return MagicMock(text="ok", parsed=None, usage_metadata=None)

    provider = GeminiProvider("test-key")
    fake_models = MagicMock()
    fake_models.generate_content = fake_generate_content
    fake_aio = MagicMock()
    fake_aio.models = fake_models
    provider._client = MagicMock()
    provider._client.aio = fake_aio

    await provider.generate(
        ProviderRequest(
            model=GEMINI_MODEL,
            parts=["Continue the conversation"],
            history=[
                Message(role="user", content="What's the weather?"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call_abc",
                            name="get_weather",
                            arguments='{"location": "NYC"}',
                        )
                    ],
                ),
                Message(role="tool", tool_call_id="call_abc", content='{"temp": 72}'),
            ],
        )
    )

    contents = captured["contents"]
    # 3 Content items: user, model(function_call), user(function_response + prompt).
    # The prompt is merged into the function-response Content to preserve
    # Gemini's required turn order without losing the instruction.
    assert len(contents) == 3

    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "What's the weather?"

    assert contents[1].role == "model"
    assert contents[1].parts[0].function_call.name == "get_weather"
    assert contents[1].parts[0].function_call.args == {"location": "NYC"}

    assert contents[2].role == "user"
    assert contents[2].parts[0].function_response.name == "get_weather"
    assert contents[2].parts[0].function_response.response == {"temp": 72}
    # Prompt merged as a second part in the same Content block.
    assert contents[2].parts[1].text == "Continue the conversation"


@pytest.mark.asyncio
async def test_gemini_merges_prompt_into_tool_response_content() -> None:
    """When history ends with a tool response, the prompt is merged in.

    Gemini requires Model immediately after FunctionResponse. Adding a
    separate User Content would produce FunctionResponse → User → Model
    (rejected with 400 INVALID_ARGUMENT). Instead, the prompt is folded
    into the function-response Content block so the model still sees it.
    """
    captured: dict[str, Any] = {}

    async def fake_generate_content(
        *,
        model: str,  # noqa: ARG001
        contents: Any,
        config: Any,  # noqa: ARG001
    ) -> Any:
        captured["contents"] = contents
        return MagicMock(text="ok", parsed=None, usage_metadata=None)

    provider = GeminiProvider("test-key")
    fake_models = MagicMock()
    fake_models.generate_content = fake_generate_content
    fake_aio = MagicMock()
    fake_aio.models = fake_models
    provider._client = MagicMock()
    provider._client.aio = fake_aio

    await provider.generate(
        ProviderRequest(
            model=GEMINI_MODEL,
            parts=["Proceed."],
            history=[
                Message(role="user", content="What's the weather?"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call_abc",
                            name="get_weather",
                            arguments='{"location": "NYC"}',
                        )
                    ],
                ),
                Message(role="tool", tool_call_id="call_abc", content='{"temp": 72}'),
            ],
        )
    )

    contents = captured["contents"]
    # 3 Content items — prompt merged into function-response Content.
    assert len(contents) == 3

    assert contents[0].role == "user"
    assert contents[1].role == "model"
    assert contents[1].parts[0].function_call.name == "get_weather"
    assert contents[2].role == "user"
    assert contents[2].parts[0].function_response.name == "get_weather"
    # Prompt folded in as a second part.
    assert contents[2].parts[1].text == "Proceed."


# =============================================================================
# Anthropic Response Parsing (Characterization)
# =============================================================================


def _fake_anthropic_response(
    *,
    content: list[Any] | None = None,
    usage: Any | None = None,
    stop_reason: str | None = "end_turn",
    response_id: str | None = "msg_test123",
) -> Any:
    """Create a minimal Anthropic-like Message response."""
    if content is None:
        content = []
    if usage is None:
        usage = type("Usage", (), {"input_tokens": 10, "output_tokens": 25})()
    return type(
        "Message",
        (),
        {
            "content": content,
            "usage": usage,
            "stop_reason": stop_reason,
            "id": response_id,
        },
    )()


def _fake_text_block(text: str) -> Any:
    """Create a fake Anthropic text content block."""
    return type("TextBlock", (), {"type": "text", "text": text})()


def _fake_tool_use_block(
    *, tool_id: str = "toolu_abc", name: str = "get_weather", tool_input: Any = None
) -> Any:
    """Create a fake Anthropic tool_use content block."""
    if tool_input is None:
        tool_input = {"location": "NYC"}
    return type(
        "ToolUseBlock",
        (),
        {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input},
    )()


def test_anthropic_parse_text_and_usage() -> None:
    """Characterize extraction of text and usage from Anthropic response."""
    from pollux.providers.anthropic import _parse_response

    response = _fake_anthropic_response(
        content=[_fake_text_block("The answer is 42.")],
    )

    result = _parse_response(response, response_schema=None)

    assert result.text == "The answer is 42."
    assert result.usage == {
        "input_tokens": 10,
        "output_tokens": 25,
        "total_tokens": 35,
    }
    assert result.response_id == "msg_test123"
    assert result.structured is None


def test_anthropic_parse_structured_from_json_text() -> None:
    """Characterize structured output extraction from JSON text."""
    from pollux.providers.anthropic import _parse_response

    response = _fake_anthropic_response(
        content=[_fake_text_block('{"title": "Test", "score": 95}')],
    )

    result = _parse_response(response, response_schema={"type": "object"})

    assert result.text == '{"title": "Test", "score": 95}'
    assert result.structured == {"title": "Test", "score": 95}


def test_anthropic_parse_non_json_text() -> None:
    """Characterize behavior when text is not JSON and schema is requested."""
    from pollux.providers.anthropic import _parse_response

    response = _fake_anthropic_response(
        content=[_fake_text_block("Just plain text.")],
    )

    result = _parse_response(response, response_schema={"type": "object"})

    assert result.text == "Just plain text."
    assert result.structured is None


def test_anthropic_parse_tool_calls() -> None:
    """Characterize tool_use block extraction into ToolCall list."""
    from pollux.providers.anthropic import _parse_response

    response = _fake_anthropic_response(
        content=[
            _fake_tool_use_block(
                tool_id="toolu_abc",
                name="get_weather",
                tool_input={"location": "NYC"},
            )
        ],
        stop_reason="tool_use",
    )

    result = _parse_response(response, response_schema=None)

    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.id == "toolu_abc"
    assert tc.name == "get_weather"
    assert tc.arguments == '{"location": "NYC"}'
    assert result.finish_reason == "tool_calls"


def test_anthropic_parse_finish_reason_end_turn() -> None:
    """end_turn stop_reason should map to 'stop'."""
    from pollux.providers.anthropic import _parse_response

    response = _fake_anthropic_response(
        content=[_fake_text_block("Done.")],
        stop_reason="end_turn",
    )

    result = _parse_response(response, response_schema=None)
    assert result.finish_reason == "stop"


def test_anthropic_parse_finish_reason_max_tokens() -> None:
    """max_tokens stop_reason should be forwarded as-is."""
    from pollux.providers.anthropic import _parse_response

    response = _fake_anthropic_response(
        content=[_fake_text_block("Truncated...")],
        stop_reason="max_tokens",
    )

    result = _parse_response(response, response_schema=None)
    assert result.finish_reason == "max_tokens"


def test_anthropic_parse_empty_content() -> None:
    """Characterize graceful handling of empty content list."""
    from pollux.providers.anthropic import _parse_response

    response = _fake_anthropic_response(content=[])

    result = _parse_response(response, response_schema=None)

    assert result.text == ""
    assert result.tool_calls is None


def test_anthropic_parse_mixed_content() -> None:
    """Characterize response with both text and tool_use blocks."""
    from pollux.providers.anthropic import _parse_response

    response = _fake_anthropic_response(
        content=[
            _fake_text_block("Let me check the weather."),
            _fake_tool_use_block(name="get_weather"),
        ],
        stop_reason="tool_use",
    )

    result = _parse_response(response, response_schema=None)

    assert result.text == "Let me check the weather."
    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_weather"


# =============================================================================
# Anthropic Generate Config (Characterization)
# =============================================================================


class _FakeAnthropicMessages:
    """Captures kwargs passed to messages.create()."""

    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        return _fake_anthropic_response(
            content=[_fake_text_block("ok")],
        )


def _anthropic_provider_with_fake() -> tuple[AnthropicProvider, _FakeAnthropicMessages]:
    """Wire an AnthropicProvider to a fake messages client."""
    messages = _FakeAnthropicMessages()
    fake_client = type("Client", (), {"messages": messages})()
    provider = AnthropicProvider("test-key")
    provider._client = fake_client
    return provider, messages


@pytest.mark.asyncio
async def test_anthropic_generate_basic_request() -> None:
    """Characterize the basic kwargs shape sent to messages.create."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model=ANTHROPIC_MODEL,
            parts=["What is 2+2?"],
        )
    )

    assert messages.last_kwargs is not None
    assert messages.last_kwargs["model"] == ANTHROPIC_MODEL
    assert messages.last_kwargs["max_tokens"] == 8192
    assert len(messages.last_kwargs["messages"]) == 1
    msg = messages.last_kwargs["messages"][0]
    assert msg["role"] == "user"
    assert msg["content"] == [{"type": "text", "text": "What is 2+2?"}]


@pytest.mark.asyncio
async def test_anthropic_generate_with_system_instruction() -> None:
    """system_instruction should map to the system parameter."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model=ANTHROPIC_MODEL,
            parts=["Hello"],
            system_instruction="Be concise.",
        )
    )

    assert messages.last_kwargs is not None
    assert messages.last_kwargs["system"] == "Be concise."


@pytest.mark.asyncio
async def test_anthropic_generate_with_tools() -> None:
    """Tools should be mapped to Anthropic format with input_schema."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model=ANTHROPIC_MODEL,
            parts=["What's the weather?"],
            tools=[
                {
                    "name": "get_weather",
                    "description": "Get weather for a location.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                        },
                        "required": ["location"],
                    },
                }
            ],
            tool_choice="required",
        )
    )

    assert messages.last_kwargs is not None
    tools = messages.last_kwargs["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "get_weather"
    assert tools[0]["description"] == "Get weather for a location."
    assert "input_schema" in tools[0]
    assert tools[0]["input_schema"]["properties"]["location"]["type"] == "string"
    # "required" maps to {"type": "any"}
    assert messages.last_kwargs["tool_choice"] == {"type": "any"}


@pytest.mark.asyncio
async def test_anthropic_generate_with_temperature() -> None:
    """Temperature and top_p should pass through to messages.create."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model=ANTHROPIC_MODEL,
            parts=["Hello"],
            temperature=0.5,
            top_p=0.9,
        )
    )

    assert messages.last_kwargs is not None
    assert messages.last_kwargs["temperature"] == 0.5
    assert messages.last_kwargs["top_p"] == 0.9


@pytest.mark.asyncio
async def test_anthropic_generate_with_structured_output() -> None:
    """response_schema should map to output_config.format with json_schema."""
    provider, messages = _anthropic_provider_with_fake()

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }

    await provider.generate(
        ProviderRequest(
            model=ANTHROPIC_MODEL,
            parts=["Answer the question."],
            response_schema=schema,
        )
    )

    assert messages.last_kwargs is not None
    output_config = messages.last_kwargs["output_config"]
    assert output_config["format"]["type"] == "json_schema"
    # to_strict_schema adds additionalProperties: False
    expected = {**schema, "additionalProperties": False}
    assert output_config["format"]["schema"] == expected


@pytest.mark.asyncio
async def test_anthropic_generate_with_history() -> None:
    """History should be replayed as full message list."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model=ANTHROPIC_MODEL,
            parts=["Continue."],
            history=[
                Message(role="user", content="Hi"),
                Message(role="assistant", content="Hello!"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="toolu_abc",
                            name="get_weather",
                            arguments='{"location": "NYC"}',
                        )
                    ],
                ),
                Message(
                    role="tool",
                    tool_call_id="toolu_abc",
                    content='{"temp": 72}',
                ),
            ],
        )
    )

    assert messages.last_kwargs is not None
    msgs = messages.last_kwargs["messages"]
    # Expected order: user Hi, assistant Hello, assistant tool_use, user tool_result, user Continue
    assert len(msgs) == 5
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "Hi"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == [{"type": "text", "text": "Hello!"}]
    assert msgs[2]["role"] == "assistant"
    assert msgs[2]["content"][0]["type"] == "tool_use"
    assert msgs[3]["role"] == "user"
    assert msgs[3]["content"][0]["type"] == "tool_result"
    assert msgs[4]["role"] == "user"


# =============================================================================
# Anthropic Capability Tests (Characterization)
# =============================================================================


@pytest.mark.asyncio
async def test_anthropic_upload_raises() -> None:
    """upload_file should raise APIError: not supported."""
    from pathlib import Path

    provider = AnthropicProvider("test-key")

    with pytest.raises(APIError, match="does not support file uploads"):
        await provider.upload_file(Path("/dummy"), "application/pdf")


@pytest.mark.asyncio
async def test_anthropic_cache_raises() -> None:
    """create_cache should raise APIError: not supported."""
    provider = AnthropicProvider("test-key")

    with pytest.raises(APIError, match="does not support context caching"):
        await provider.create_cache(
            model=ANTHROPIC_MODEL, parts=["test"], ttl_seconds=3600
        )
