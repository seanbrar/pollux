"""Provider contract characterization tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pollux.errors import APIError, ConfigurationError
from pollux.providers.anthropic import AnthropicProvider
from pollux.providers.models import (
    Message,
    ProviderFileAsset,
    ProviderRequest,
    ToolCall,
)
from tests.conftest import (
    ANTHROPIC_MODEL,
)

pytestmark = pytest.mark.contract


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


def _fake_thinking_block(
    *,
    thinking: str = "Let me reason this through.",
    signature: str = "sig_abc",
) -> Any:
    """Create a fake Anthropic thinking block."""
    return type(
        "ThinkingBlock",
        (),
        {"type": "thinking", "thinking": thinking, "signature": signature},
    )()


def _fake_redacted_thinking_block(*, data: str = "redacted_blob") -> Any:
    """Create a fake Anthropic redacted thinking block."""
    return type(
        "RedactedThinkingBlock", (), {"type": "redacted_thinking", "data": data}
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


def test_anthropic_parse_extracts_cached_tokens() -> None:
    """cache_read_input_tokens should appear as cached_tokens in usage."""
    from pollux.providers.anthropic import _parse_response

    usage_obj = type(
        "Usage",
        (),
        {
            "input_tokens": 50,
            "output_tokens": 25,
            "cache_read_input_tokens": 9_000,
        },
    )()
    response = _fake_anthropic_response(
        content=[_fake_text_block("ok")],
        usage=usage_obj,
    )

    result = _parse_response(response, response_schema=None)

    assert result.usage["cached_tokens"] == 9_000
    # Anthropic semantics: cache reads are reported separately from input_tokens.
    assert result.usage["input_tokens"] == 50


def test_anthropic_parse_preserves_unknown_blocks_as_artifacts() -> None:
    """Provider-specific server-tool blocks should remain inspectable."""
    from pollux.providers.anthropic import _parse_response

    server_block = type(
        "ServerToolBlock",
        (),
        {"type": "server_tool_use", "id": "srv_123", "name": "web_search"},
    )()
    response = _fake_anthropic_response(
        content=[_fake_text_block("ok"), server_block],
    )

    result = _parse_response(response, response_schema=None)

    assert result.artifacts == {
        "content_blocks": [
            {"id": "srv_123", "name": "web_search", "type": "server_tool_use"}
        ]
    }


def test_anthropic_parse_omits_cached_tokens_when_absent() -> None:
    """Missing cache_read_input_tokens should not add cached_tokens."""
    from pollux.providers.anthropic import _parse_response

    response = _fake_anthropic_response(
        content=[_fake_text_block("ok")],
    )

    result = _parse_response(response, response_schema=None)

    assert "cached_tokens" not in result.usage


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


def test_anthropic_parse_finish_reason() -> None:
    """Characterize stop_reason → finish_reason mapping."""
    from pollux.providers.anthropic import _parse_response

    cases = [("end_turn", "stop"), ("max_tokens", "max_tokens")]
    for stop_reason, expected in cases:
        response = _fake_anthropic_response(
            content=[_fake_text_block("ok")],
            stop_reason=stop_reason,
        )
        result = _parse_response(response, response_schema=None)
        assert result.finish_reason == expected, f"stop_reason={stop_reason}"


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


def test_anthropic_parse_extracts_reasoning_and_thinking_state() -> None:
    """Thinking blocks should populate reasoning + provider_state for replay."""
    from pollux.providers.anthropic import _parse_response

    response = _fake_anthropic_response(
        content=[
            _fake_thinking_block(thinking="First line", signature="sig1"),
            _fake_redacted_thinking_block(data="opaque"),
            _fake_text_block("Final answer."),
        ]
    )

    result = _parse_response(response, response_schema=None)

    assert result.reasoning == "First line"
    assert result.provider_state == {
        "anthropic_thinking_blocks": [
            {"type": "thinking", "thinking": "First line", "signature": "sig1"},
            {"type": "redacted_thinking", "data": "opaque"},
        ]
    }


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
    assert messages.last_kwargs["max_tokens"] == 16384
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
            implicit_caching=True,
        )
    )

    assert messages.last_kwargs is not None
    assert messages.last_kwargs["system"] == "Be concise."
    assert messages.last_kwargs["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_anthropic_generate_with_implicit_caching_disabled() -> None:
    """Disabling implicit_caching omits Anthropic cache_control."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model=ANTHROPIC_MODEL,
            parts=["Hello"],
            system_instruction="Be concise.",
            implicit_caching=False,
        )
    )

    assert messages.last_kwargs is not None
    assert messages.last_kwargs["system"] == "Be concise."
    assert "cache_control" not in messages.last_kwargs


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
async def test_anthropic_generate_maps_reasoning_to_output_effort_and_manual_thinking() -> (
    None
):
    """Non-adaptive Anthropic models should use manual thinking budgets."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model="claude-haiku-4-5",
            parts=["Think."],
            reasoning_effort="high",
        )
    )

    assert messages.last_kwargs is not None
    assert messages.last_kwargs["output_config"]["effort"] == "high"
    assert messages.last_kwargs["thinking"] == {
        "type": "enabled",
        "budget_tokens": 10240,
    }


@pytest.mark.asyncio
async def test_anthropic_generate_maps_reasoning_to_adaptive_for_opus_and_sonnet() -> (
    None
):
    """Opus 4.6 and Sonnet 4.6 should use adaptive thinking mode."""
    provider, messages = _anthropic_provider_with_fake()

    for model in ("claude-opus-4-6-20260219", "claude-sonnet-4-6-20260219"):
        await provider.generate(
            ProviderRequest(
                model=model,
                parts=["Think."],
                reasoning_effort="medium",
            )
        )

        assert messages.last_kwargs is not None
        assert messages.last_kwargs["output_config"]["effort"] == "medium"
        assert messages.last_kwargs["thinking"] == {"type": "adaptive"}


@pytest.mark.asyncio
async def test_anthropic_generate_maps_reasoning_budget_tokens_to_thinking_budget() -> (
    None
):
    """Budget-based reasoning should pass through Anthropic's budget_tokens knob."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model="claude-haiku-4-5",
            parts=["Think."],
            reasoning_budget_tokens=1024,
        )
    )

    assert messages.last_kwargs is not None
    assert "output_config" not in messages.last_kwargs
    assert messages.last_kwargs["thinking"] == {
        "type": "enabled",
        "budget_tokens": 1024,
    }


@pytest.mark.asyncio
async def test_anthropic_generate_reasoning_with_tools_adds_interleaved_header_for_manual() -> (
    None
):
    """Reasoning + tools should opt into interleaved-thinking beta header for non-adaptive models."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model="claude-sonnet-4-5",
            parts=["Need tool help."],
            reasoning_effort="low",
            tools=[{"name": "get_weather", "parameters": {"type": "object"}}],
        )
    )

    assert messages.last_kwargs is not None
    assert messages.last_kwargs["extra_headers"] == {
        "anthropic-beta": "files-api-2025-04-14,interleaved-thinking-2025-05-14"
    }


@pytest.mark.asyncio
async def test_anthropic_generate_reasoning_with_tools_omits_header_for_adaptive() -> (
    None
):
    """Reasoning + tools should omit beta header for adaptive models."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model="claude-sonnet-4-6-20260219",
            parts=["Need tool help."],
            reasoning_effort="low",
            tools=[{"name": "get_weather", "parameters": {"type": "object"}}],
        )
    )

    assert messages.last_kwargs is not None
    assert messages.last_kwargs["extra_headers"] == {
        "anthropic-beta": "files-api-2025-04-14"
    }


@pytest.mark.asyncio
async def test_anthropic_generate_uses_adaptive_for_opus_4_7() -> None:
    """Opus 4.7 rejects manual thinking and should route through adaptive."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model="claude-opus-4-7",
            parts=["Think."],
            reasoning_effort="max",
        )
    )

    assert messages.last_kwargs is not None
    assert messages.last_kwargs["output_config"]["effort"] == "max"
    assert messages.last_kwargs["thinking"] == {"type": "adaptive"}


@pytest.mark.asyncio
async def test_anthropic_provider_options_merge_and_overlap() -> None:
    """Raw Anthropic options should merge unless they overlap managed fields."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model=ANTHROPIC_MODEL,
            parts=["Hello"],
            provider_options={"metadata": {"user_id": "pollux-test"}},
        )
    )

    assert messages.last_kwargs is not None
    assert messages.last_kwargs["metadata"] == {"user_id": "pollux-test"}

    with pytest.raises(ConfigurationError, match="overlap"):
        await provider.generate(
            ProviderRequest(
                model=ANTHROPIC_MODEL,
                parts=["Hello"],
                provider_options={"max_tokens": 64},
            )
        )


@pytest.mark.asyncio
async def test_anthropic_generate_rejects_unknown_reasoning_effort() -> None:
    """Anthropic effort mapping should fail fast on unsupported values."""
    provider, _messages = _anthropic_provider_with_fake()

    with pytest.raises(APIError, match="Unsupported reasoning_effort"):
        await provider.generate(
            ProviderRequest(
                model=ANTHROPIC_MODEL,
                parts=["Think."],
                reasoning_effort="16000",
            )
        )


@pytest.mark.asyncio
async def test_anthropic_generate_rejects_max_effort_on_non_opus_4_6() -> None:
    """Anthropic 'max' effort requires Opus 4.6."""
    from pollux.errors import ConfigurationError

    provider, _messages = _anthropic_provider_with_fake()

    with pytest.raises(ConfigurationError, match=r"supported on Claude Opus 4\.6\+"):
        await provider.generate(
            ProviderRequest(
                model="claude-sonnet-4-6",
                parts=["Think."],
                reasoning_effort="max",
            )
        )


@pytest.mark.asyncio
async def test_anthropic_generate_max_tokens_default_and_override() -> None:
    """max_tokens defaults to 16384 but respects explicit overrides."""
    provider, messages = _anthropic_provider_with_fake()

    # Default
    await provider.generate(ProviderRequest(model=ANTHROPIC_MODEL, parts=["Hello"]))
    assert messages.last_kwargs is not None
    assert messages.last_kwargs["max_tokens"] == 16384

    # Override
    await provider.generate(
        ProviderRequest(model=ANTHROPIC_MODEL, parts=["Hello"], max_tokens=25000)
    )
    assert messages.last_kwargs is not None
    assert messages.last_kwargs["max_tokens"] == 25000


@pytest.mark.asyncio
async def test_anthropic_generate_with_history() -> None:
    """History with tool turns merges consecutive same-role messages.

    Anthropic requires strict user/assistant alternation.  Two adjacent
    assistant messages (text then tool_use) must be merged into one, and
    the trailing tool_result (user) + current prompt (user) must be
    merged so we never send consecutive same-role messages.
    """
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

    # After merging: user → assistant (text + tool_use) → user (tool_result + prompt)
    assert len(msgs) == 3
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "Hi"

    # Assistant: text "Hello!" merged with tool_use block
    assert msgs[1]["role"] == "assistant"
    assert len(msgs[1]["content"]) == 2
    assert msgs[1]["content"][0] == {"type": "text", "text": "Hello!"}
    assert msgs[1]["content"][1]["type"] == "tool_use"
    assert msgs[1]["content"][1]["name"] == "get_weather"

    # User: tool_result merged with current prompt
    assert msgs[2]["role"] == "user"
    assert len(msgs[2]["content"]) == 2
    assert msgs[2]["content"][0]["type"] == "tool_result"
    assert msgs[2]["content"][0]["tool_use_id"] == "toolu_abc"
    assert msgs[2]["content"][1] == {"type": "text", "text": "Continue."}


@pytest.mark.asyncio
async def test_anthropic_generate_history_replays_preserved_thinking_blocks() -> None:
    """History provider_state should replay signed thinking blocks verbatim."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model=ANTHROPIC_MODEL,
            parts=[],
            history=[
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(id="toolu_abc", name="get_weather", arguments="{}")
                    ],
                ),
                Message(role="tool", tool_call_id="toolu_abc", content='{"temp": 72}'),
            ],
            provider_state={
                "history": [
                    {
                        "anthropic_thinking_blocks": [
                            {
                                "type": "thinking",
                                "thinking": "I should call the weather tool.",
                                "signature": "sig_123",
                            },
                            {"type": "redacted_thinking", "data": "blob"},
                        ]
                    },
                    None,
                ]
            },
        )
    )

    assert messages.last_kwargs is not None
    assistant_blocks = messages.last_kwargs["messages"][0]["content"]
    assert assistant_blocks[0] == {
        "type": "thinking",
        "thinking": "I should call the weather tool.",
        "signature": "sig_123",
    }
    assert assistant_blocks[1] == {"type": "redacted_thinking", "data": "blob"}
    assert assistant_blocks[2]["type"] == "tool_use"


@pytest.mark.asyncio
async def test_anthropic_generate_parallel_tool_results_merged() -> None:
    """Multiple tool results (parallel tool calls) merge into one user message."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model=ANTHROPIC_MODEL,
            parts=["Summarize both."],
            history=[
                Message(role="user", content="Weather and time?"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(id="t1", name="get_weather", arguments="{}"),
                        ToolCall(id="t2", name="get_time", arguments="{}"),
                    ],
                ),
                Message(role="tool", tool_call_id="t1", content='{"temp": 72}'),
                Message(role="tool", tool_call_id="t2", content='{"time": "3pm"}'),
            ],
        )
    )

    assert messages.last_kwargs is not None
    msgs = messages.last_kwargs["messages"]

    # user → assistant (2 tool_use) → user (2 tool_results + prompt)
    assert len(msgs) == 3
    assert msgs[2]["role"] == "user"
    assert len(msgs[2]["content"]) == 3
    assert msgs[2]["content"][0]["type"] == "tool_result"
    assert msgs[2]["content"][0]["tool_use_id"] == "t1"
    assert msgs[2]["content"][1]["type"] == "tool_result"
    assert msgs[2]["content"][1]["tool_use_id"] == "t2"
    assert msgs[2]["content"][2] == {"type": "text", "text": "Summarize both."}


@pytest.mark.asyncio
async def test_anthropic_generate_continuation_no_prompt() -> None:
    """continue_tool pattern: history ends with tool_result, no new prompt."""
    provider, messages = _anthropic_provider_with_fake()

    await provider.generate(
        ProviderRequest(
            model=ANTHROPIC_MODEL,
            parts=[],  # No prompt (continue_tool sends prompt=None → [])
            history=[
                Message(role="user", content="What's the weather?"),
                Message(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(id="t1", name="get_weather", arguments="{}"),
                    ],
                ),
                Message(role="tool", tool_call_id="t1", content='{"temp": 72}'),
            ],
        )
    )

    assert messages.last_kwargs is not None
    msgs = messages.last_kwargs["messages"]

    # user → assistant (tool_use) → user (tool_result only, no extra empty message)
    assert len(msgs) == 3
    assert msgs[2]["role"] == "user"
    assert len(msgs[2]["content"]) == 1
    assert msgs[2]["content"][0]["type"] == "tool_result"


# =============================================================================
# Anthropic Capability Tests (Characterization)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model", ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"]
)
async def test_anthropic_validate_request_rejects_reasoning_on_claude_3(
    model: str,
) -> None:
    """Claude 3.0/3.5 lack extended thinking; a reasoning request must fail fast."""
    provider = AnthropicProvider("test-key")

    with pytest.raises(ConfigurationError, match="extended thinking"):
        await provider.validate_request(
            ProviderRequest(model=model, parts=["Think hard."], reasoning_effort="high")
        )
    with pytest.raises(ConfigurationError, match="extended thinking"):
        await provider.validate_request(
            ProviderRequest(
                model=model, parts=["Think hard."], reasoning_budget_tokens=2048
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["claude-3-7-sonnet-20250219", ANTHROPIC_MODEL])
async def test_anthropic_validate_request_allows_reasoning_on_thinking_models(
    model: str,
) -> None:
    """Claude 3.7 and 4.x support thinking; the 3.7 prefix must not be rejected."""
    provider = AnthropicProvider("test-key")

    # Returns None (no raise) when the model supports extended thinking.
    await provider.validate_request(
        ProviderRequest(model=model, parts=["Think hard."], reasoning_effort="high")
    )


@pytest.mark.asyncio
async def test_anthropic_validate_request_allows_non_reasoning_on_claude_3() -> None:
    """A plain request on a Claude 3 model must pass validation unchanged."""
    provider = AnthropicProvider("test-key")

    await provider.validate_request(
        ProviderRequest(model="claude-3-5-sonnet-20241022", parts=["Hello."])
    )


@pytest.mark.asyncio
async def test_anthropic_upload_raises() -> None:
    """upload_file should raise APIError on network or IO failure."""

    provider = AnthropicProvider("test-key")

    with pytest.raises(APIError, match="Anthropic upload failed"):
        await provider.upload_file(Path("/dummy"), "application/pdf")


@pytest.mark.asyncio
async def test_anthropic_upload_success(tmp_path: Any) -> None:
    """Characterize successful Anthropic file upload."""

    class _FakeBetaFiles:
        def __init__(self) -> None:
            self.last_kwargs: dict[str, Any] = {}

        async def upload(self, **kwargs: Any) -> Any:
            self.last_kwargs = kwargs
            return type("Result", (), {"id": "file_123"})()

    fake_files = _FakeBetaFiles()
    fake_client = type(
        "Client", (), {"beta": type("Beta", (), {"files": fake_files})()}
    )()

    provider = AnthropicProvider("test-key")
    provider._client = fake_client

    file_path = tmp_path / "test.jpg"
    file_path.write_bytes(b"image data")

    asset = await provider.upload_file(file_path, "image/jpeg")

    assert isinstance(asset, ProviderFileAsset)
    assert asset.file_id == "file_123"
    assert asset.provider == "anthropic"
    assert asset.mime_type == "image/jpeg"

    assert fake_files.last_kwargs["file"] == ("test.jpg", b"image data", "image/jpeg")
    assert fake_files.last_kwargs["extra_headers"] == {
        "anthropic-beta": "files-api-2025-04-14"
    }


@pytest.mark.asyncio
async def test_anthropic_upload_rejects_text_csv_before_dispatch(tmp_path: Any) -> None:
    """Anthropic accepts only plaintext document files, not all text/* MIME types."""

    class _FakeBetaFiles:
        upload_called = False

        async def upload(self, **kwargs: Any) -> Any:  # noqa: ARG002
            self.upload_called = True
            return type("Result", (), {"id": "file_123"})()

    fake_files = _FakeBetaFiles()
    fake_client = type(
        "Client", (), {"beta": type("Beta", (), {"files": fake_files})()}
    )()

    provider = AnthropicProvider("test-key")
    provider._client = fake_client

    file_path = tmp_path / "data.csv"
    file_path.write_text("a,b\n1,2\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Unsupported mime type"):
        await provider.upload_file(file_path, "text/csv")
    assert fake_files.upload_called is False


@pytest.mark.asyncio
async def test_anthropic_generate_resolves_file_assets() -> None:
    """ProviderFileAsset parts should be resolved to corresponding Anthropic source blocks."""

    provider, messages = _anthropic_provider_with_fake()

    # Mix of image and pdf
    await provider.generate(
        ProviderRequest(
            model=ANTHROPIC_MODEL,
            parts=[
                ProviderFileAsset(
                    file_id="abc", provider="anthropic", mime_type="image/jpeg"
                ),
                ProviderFileAsset(
                    file_id="xyz", provider="anthropic", mime_type="application/pdf"
                ),
                "Please describe both.",
            ],
        )
    )

    assert messages.last_kwargs is not None
    msgs = messages.last_kwargs["messages"]
    assert len(msgs) == 1
    content = msgs[0]["content"]

    assert content[0] == {
        "type": "image",
        "source": {
            "type": "file",
            "file_id": "abc",
        },
    }
    assert content[1] == {
        "type": "document",
        "source": {
            "type": "file",
            "file_id": "xyz",
        },
    }
    assert content[2] == {"type": "text", "text": "Please describe both."}

    # Files API requires the beta header for messages.create too
    assert (
        messages.last_kwargs["extra_headers"]["anthropic-beta"]
        == "files-api-2025-04-14"
    )


@pytest.mark.asyncio
async def test_anthropic_cache_raises() -> None:
    """create_cache should raise APIError: not supported."""
    provider = AnthropicProvider("test-key")

    with pytest.raises(APIError, match="does not support context caching"):
        await provider.create_cache(
            model=ANTHROPIC_MODEL, parts=["test"], ttl_seconds=3600
        )
