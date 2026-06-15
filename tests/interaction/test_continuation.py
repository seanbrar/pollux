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
