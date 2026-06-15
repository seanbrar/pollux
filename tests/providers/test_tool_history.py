"""Provider contract characterization tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from pollux.interaction.continuation import Continuation, Message
from pollux.interaction.tools import ToolCall, ToolResult
from pollux.providers.gemini import GeminiProvider
from pollux.providers.openai import OpenAIProvider
from tests.conftest import (
    GEMINI_MODEL,
    OPENAI_MODEL,
)
from tests.helpers import make_interaction
from tests.providers.helpers import FakeResponses

pytestmark = pytest.mark.contract


def _openai(**kwargs: Any) -> tuple[Any, Any, Any, Any]:
    kwargs.setdefault("model", OPENAI_MODEL)
    return make_interaction(provider="openai", **kwargs)


def _gemini(**kwargs: Any) -> tuple[Any, Any, Any, Any]:
    kwargs.setdefault("model", GEMINI_MODEL)
    return make_interaction(provider="gemini", **kwargs)


# =============================================================================
# OpenAI Tool History Mapping (Characterization)
# =============================================================================


@pytest.mark.asyncio
async def test_openai_maps_tool_history_to_responses_api_format() -> None:
    """Tool messages in history should map to function_call/function_call_output."""
    responses = FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openai(
            content="Continue the conversation",
            continuation=Continuation(
                messages=(
                    Message(role="user", content="What's the weather?"),
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=(
                            ToolCall.from_text(
                                id="call_abc",
                                name="get_weather",
                                arguments_text='{"location": "NYC"}',
                            ),
                        ),
                    ),
                ),
            ),
            tool_results=[ToolResult(call_id="call_abc", content='{"temp": 72}')],
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
    responses = FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openai(
            content="Continue",
            continuation=Continuation(
                messages=(
                    Message(
                        role="assistant",
                        content="Let me check that tool.",
                        tool_calls=(
                            ToolCall.from_text(
                                id="call_abc", name="get_weather", arguments_text="{}"
                            ),
                        ),
                    ),
                ),
            ),
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
    responses = FakeResponses()
    fake_client = type("Client", (), {"responses": responses})()

    provider = OpenAIProvider("test-key")
    provider._client = fake_client

    await provider.generate(
        *_openai(
            content="Continue",
            continuation=Continuation(
                response_id="resp_prev",
                messages=(
                    Message(role="user", content="What's the weather?"),
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=(
                            ToolCall.from_text(
                                id="call_abc", name="get_weather", arguments_text="{}"
                            ),
                        ),
                    ),
                ),
            ),
            tool_results=[ToolResult(call_id="call_abc", content='{"temp": 72}')],
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
        *_gemini(
            content="Continue the conversation",
            continuation=Continuation(
                messages=(
                    Message(role="user", content="What's the weather?"),
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=(
                            ToolCall.from_text(
                                id="call_abc",
                                name="get_weather",
                                arguments_text='{"location": "NYC"}',
                            ),
                        ),
                    ),
                ),
            ),
            tool_results=[ToolResult(call_id="call_abc", content='{"temp": 72}')],
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
        *_gemini(
            content="Proceed.",
            continuation=Continuation(
                messages=(
                    Message(role="user", content="What's the weather?"),
                    Message(
                        role="assistant",
                        content="",
                        tool_calls=(
                            ToolCall.from_text(
                                id="call_abc",
                                name="get_weather",
                                arguments_text='{"location": "NYC"}',
                            ),
                        ),
                    ),
                ),
            ),
            tool_results=[ToolResult(call_id="call_abc", content='{"temp": 72}')],
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
