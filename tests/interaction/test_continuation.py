"""Unit tests for portable messages and opaque continuations."""

from __future__ import annotations

from copy import deepcopy

import pytest

from pollux.errors import ConfigurationError, PolluxError
from pollux.interaction.continuation import (
    SCHEMA_VERSION,
    Continuation,
    Message,
    build_continuation,
)
from pollux.interaction.input import Input
from pollux.interaction.tools import ToolCall
from pollux.providers.models import ProviderResponse
from tests.helpers import make_continuation

pytestmark = pytest.mark.unit


def test_continuation_roundtrips_and_defensively_serializes() -> None:
    original = make_continuation(
        messages=(
            Message(role="user", content="hi"),
            Message(
                role="assistant",
                tool_calls=(
                    ToolCall.from_text(id="c1", name="f", arguments_text="{}"),
                ),
            ),
        ),
        response_id="r1",
        provider="anthropic",
        provider_state={"secret": {"value": 1}},
    )
    blob = original.to_jsonable()
    restored = Continuation.from_jsonable(blob, expected_provider="anthropic")
    assert restored.to_jsonable() == blob
    assert blob["version"] == SCHEMA_VERSION == 2

    mutated = deepcopy(blob)
    mutated["provider_state"]["secret"]["value"] = 99
    assert original.to_jsonable()["provider_state"]["secret"]["value"] == 1


def test_continuation_has_no_public_constructor_or_replay_fields() -> None:
    with pytest.raises(TypeError, match="created by Pollux"):
        Continuation()
    continuation = make_continuation(provider="openai")
    for name in ("messages", "response_id", "provider", "provider_state"):
        assert not hasattr(continuation, name)
    assert not hasattr(Continuation, "from_openai_messages")
    assert not hasattr(continuation, "to_openai_messages")


@pytest.mark.parametrize("version", [1, SCHEMA_VERSION + 1, None])
def test_continuation_rejects_incompatible_versions(version: int | None) -> None:
    with pytest.raises(PolluxError, match="Incompatible continuation"):
        Continuation.from_jsonable(
            {"version": version, "provider": "openai", "messages": []}
        )


def test_continuation_rejects_missing_or_mismatched_provider() -> None:
    with pytest.raises(PolluxError, match="missing provider"):
        Continuation.from_jsonable({"version": SCHEMA_VERSION, "messages": []})
    blob = make_continuation(provider="anthropic").to_jsonable()
    with pytest.raises(PolluxError, match="does not match"):
        Continuation.from_jsonable(blob, expected_provider="openai")


@pytest.mark.parametrize(
    "message",
    [
        Message(role="user", content="question"),
        Message(role="assistant", content="answer"),
        Message(
            role="assistant",
            tool_calls=(ToolCall.from_text(id="c1", name="lookup"),),
        ),
        Message(role="tool", tool_call_id="c1", content=""),
    ],
)
def test_portable_message_shapes_roundtrip(message: Message) -> None:
    assert Message.from_jsonable(message.to_jsonable()) == message


@pytest.mark.parametrize(
    "kwargs",
    [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": ""},
        {"role": "user", "content": "x", "tool_call_id": "c1"},
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": "x", "tool_call_id": "c1"},
        {"role": "tool", "content": "result"},
        {
            "role": "tool",
            "content": "result",
            "tool_call_id": "c1",
            "tool_calls": [ToolCall.from_text(id="nested", name="bad")],
        },
    ],
)
def test_rejects_nonportable_message_shapes(kwargs: dict[str, object]) -> None:
    with pytest.raises(ConfigurationError):
        Message(**kwargs)  # type: ignore[arg-type]


def test_message_openai_conversion_preserves_text_and_tools() -> None:
    raw = {
        "role": "assistant",
        "content": "checking",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "lookup", "arguments": '{"q":"x"}'},
            }
        ],
    }
    assert Message.from_openai(raw).to_openai() == raw


def test_message_openai_conversion_rejects_system_role() -> None:
    with pytest.raises(ConfigurationError, match=r"Environment\.instructions"):
        Message.from_openai({"role": "system", "content": "Be concise"})


def test_successful_manual_history_creates_fresh_provider_continuation() -> None:
    continuation = build_continuation(
        Input(content="next", history=[Message(role="user", content="summary")]),
        ProviderResponse(text="answer", response_id="resp_new"),
        user_content="next",
        provider="openai",
    )
    assert continuation is not None
    serialized = continuation.to_jsonable()
    assert serialized["provider"] == "openai"
    assert serialized["response_id"] == "resp_new"


def test_manual_history_does_not_create_opaque_anthropic_thinking_state() -> None:
    continuation = build_continuation(
        Input(
            tool_results=[],
            content="continue",
            history=[Message(role="user", content="compacted summary")],
        ),
        ProviderResponse(text="answer"),
        user_content="continue",
        provider="anthropic",
    )
    assert continuation is not None
    assert "anthropic_thinking_blocks" not in str(continuation.to_jsonable())
