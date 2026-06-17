"""Unit tests for the v2 ``Continuation`` primitive."""

from __future__ import annotations

import pytest

from pollux.errors import PolluxError
from pollux.interaction.continuation import SCHEMA_VERSION, Continuation, Message
from pollux.interaction.tools import ToolCall

pytestmark = pytest.mark.unit


def test_continuation_roundtrips_through_jsonable():
    cont = Continuation(
        messages=(
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                content="",
                tool_calls=(
                    ToolCall.from_text(id="c1", name="f", arguments_text='{"a": 1}'),
                ),
            ),
        ),
        response_id="r1",
        provider="anthropic",
    )
    restored = Continuation.from_jsonable(cont.to_jsonable())
    assert restored.response_id == "r1"
    assert restored.provider == "anthropic"
    assert restored.messages[0].content == "hi"
    assert restored.messages[1].tool_calls[0].name == "f"
    assert restored.messages[1].tool_calls[0].arguments == {"a": 1}


def test_continuation_stamps_current_schema_version():
    assert Continuation().to_jsonable()["version"] == SCHEMA_VERSION


def test_continuation_rejects_incompatible_version():
    blob = Continuation(provider="mock").to_jsonable()
    blob["version"] = SCHEMA_VERSION + 1
    with pytest.raises(PolluxError, match="Incompatible continuation"):
        Continuation.from_jsonable(blob)


def test_continuation_rejects_missing_version():
    with pytest.raises(PolluxError, match="Incompatible continuation"):
        Continuation.from_jsonable({"messages": []})


def test_continuation_rejects_provider_mismatch():
    blob = Continuation(provider="anthropic").to_jsonable()
    with pytest.raises(PolluxError, match="does not match"):
        Continuation.from_jsonable(blob, expected_provider="openai")


def test_continuation_accepts_matching_provider():
    blob = Continuation(provider="openai").to_jsonable()
    restored = Continuation.from_jsonable(blob, expected_provider="openai")
    assert restored.provider == "openai"


def test_openai_messages_import_tool_calls():
    continuation = Continuation.from_openai_messages(
        [
            {"role": "user", "content": "What is the weather?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city":"Paris"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": '{"temp_c": 21}',
            },
        ],
        provider="local",
    )

    assert continuation.provider == "local"
    assert continuation.messages[1].tool_calls[0].name == "get_weather"
    assert continuation.messages[1].tool_calls[0].arguments_dict() == {"city": "Paris"}
    assert continuation.messages[2].tool_call_id == "call_1"


def test_openai_messages_round_trip_tool_call_arguments_text():
    continuation = Continuation(
        messages=(
            Message(
                role="assistant",
                tool_calls=(
                    ToolCall.from_text(
                        id="call_1",
                        name="run",
                        arguments_text='{"cmd":"pwd"}',
                    ),
                ),
            ),
        )
    )

    messages = continuation.to_openai_messages()

    assert messages == [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "run", "arguments": '{"cmd":"pwd"}'},
                }
            ],
        }
    ]
