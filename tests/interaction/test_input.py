"""Unit tests for the per-turn ``Input`` primitive."""

from __future__ import annotations

import pytest

from pollux.errors import ConfigurationError
from pollux.interaction.continuation import Continuation, Message
from pollux.interaction.input import Input
from pollux.interaction.tools import ToolResult

pytestmark = pytest.mark.unit


def test_plain_content_input():
    inp = Input(content="hello")
    assert inp.content == "hello"
    assert inp.tool_results == ()


def test_coerces_tool_results_to_tuple():
    inp = Input(content="x", tool_results=[ToolResult(call_id="c1", content="ok")])
    assert isinstance(inp.tool_results, tuple)


def test_empty_content_valid_with_tool_results():
    inp = Input(tool_results=[ToolResult(call_id="c1", content="ok")])
    assert inp.content is None
    assert len(inp.tool_results) == 1


def test_rejects_empty_input():
    with pytest.raises(ConfigurationError, match="no user content"):
        Input()


def test_rejects_history_and_continuation_together():
    with pytest.raises(ConfigurationError, match="mutually exclusive"):
        Input(
            content="x",
            history=(Message(role="user", content="prior"),),
            continuation=Continuation(provider="mock"),
        )


def test_continuation_only_with_tool_results_is_valid():
    inp = Input(
        continuation=Continuation(provider="mock"),
        tool_results=[ToolResult(call_id="c1", content="ok")],
    )
    assert inp.continuation is not None
