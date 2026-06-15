"""Unit tests for v2 primitive -> ProviderRequest compilation."""

from __future__ import annotations

from typing import Any

import pytest

from pollux.config import Config
from pollux.interaction.compile import compile_request
from pollux.interaction.continuation import Continuation, Message
from pollux.interaction.environment import Environment, EnvironmentSnapshot
from pollux.interaction.input import Input
from pollux.interaction.requirements import OutputRequirements
from pollux.interaction.tools import ToolCall, ToolDeclaration, ToolResult
from pollux.source import Source
from tests.conftest import ANTHROPIC_MODEL

pytestmark = pytest.mark.unit


def _cfg() -> Config:
    return Config(provider="anthropic", model=ANTHROPIC_MODEL, use_mock=True)


def _snapshot(**kwargs: Any) -> EnvironmentSnapshot:
    return EnvironmentSnapshot.from_environment(
        Environment(**kwargs), provider="anthropic"
    )


def test_maps_environment_and_requirements():
    snapshot = _snapshot(
        instructions="sys",
        sources=[Source.from_text("DOC")],
        tools=[
            ToolDeclaration(name="f", description="d", parameters={"type": "object"})
        ],
    )
    req = compile_request(
        snapshot,
        Input(content="hi"),
        OutputRequirements(temperature=0.0, max_tokens=128),
        _cfg(),
    )
    assert req.model == ANTHROPIC_MODEL
    assert req.system_instruction == "sys"
    assert req.parts[-1] == "hi"
    assert "DOC" in req.parts
    assert req.tools == [
        {"name": "f", "description": "d", "parameters": {"type": "object"}}
    ]
    assert req.temperature == 0.0
    assert req.max_tokens == 128


def test_cache_name_excludes_source_parts():
    snapshot = _snapshot(sources=[Source.from_text("DOC")])
    req = compile_request(
        snapshot,
        Input(content="hi"),
        OutputRequirements(),
        _cfg(),
        cache_name="caches/x",
    )
    assert req.cache_name == "caches/x"
    assert req.parts == ["hi"]


def test_continuation_maps_to_history_and_response_id():
    cont = Continuation(
        messages=(
            Message(role="user", content="earlier"),
            Message(role="assistant", content="prior"),
        ),
        response_id="r1",
        provider="anthropic",
        provider_state={"k": "v"},
    )
    req = compile_request(
        _snapshot(),
        Input(content="next", continuation=cont),
        OutputRequirements(),
        _cfg(),
    )
    assert req.previous_response_id == "r1"
    assert req.provider_state == {"k": "v"}
    assert req.history is not None
    assert [m.role for m in req.history] == ["user", "assistant"]


def test_tool_results_become_tool_messages():
    cont = Continuation(
        messages=(
            Message(
                role="assistant",
                content="",
                tool_calls=(
                    ToolCall.from_text(id="c1", name="f", arguments_text="{}"),
                ),
            ),
        ),
        response_id="r1",
    )
    req = compile_request(
        _snapshot(),
        Input(continuation=cont, tool_results=[ToolResult(call_id="c1", content="42")]),
        OutputRequirements(),
        _cfg(),
    )
    assert req.history is not None
    tool_messages = [m for m in req.history if m.role == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0].content == "42"
    assert tool_messages[0].tool_call_id == "c1"


def test_provider_options_scoped_to_active_provider():
    req = compile_request(
        _snapshot(),
        Input(content="hi"),
        OutputRequirements(
            provider_options={"anthropic": {"beta": ["x"]}, "openai": {"y": 1}}
        ),
        _cfg(),
    )
    assert req.provider_options == {"beta": ["x"]}
