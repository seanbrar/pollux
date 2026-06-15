"""Unit tests for the v2 tool primitives."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from pollux.errors import ConfigurationError
from pollux.interaction.tools import ToolCall, ToolDeclaration, ToolResult

pytestmark = pytest.mark.unit


def test_tool_call_parses_valid_json_once():
    call = ToolCall.from_text(id="c1", name="f", arguments_text='{"city": "Paris"}')
    assert call.arguments == {"city": "Paris"}
    assert call.arguments_error is None
    assert call.arguments_text == '{"city": "Paris"}'


def test_tool_call_preserves_raw_text_on_invalid_json():
    call = ToolCall.from_text(id="c1", name="f", arguments_text="{not json")
    assert call.arguments is None
    assert call.arguments_error is not None
    assert call.arguments_text == "{not json"


def test_tool_call_empty_arguments_is_not_an_error():
    call = ToolCall.from_text(id="c1", name="f", arguments_text="")
    assert call.arguments is None
    assert call.arguments_error is None


def test_tool_call_to_jsonable_omits_unset_facets():
    call = ToolCall.from_text(id="c1", name="f", arguments_text='{"a": 1}')
    payload = call.to_jsonable()
    assert payload == {"id": "c1", "name": "f", "arguments_text": '{"a": 1}'}


def test_tool_call_is_frozen():
    call = ToolCall.from_text(id="c1", name="f")
    with pytest.raises(FrozenInstanceError):
        call.name = "g"  # type: ignore[misc]


def test_tool_declaration_from_flat_dict():
    decl = ToolDeclaration.from_dict(
        {"name": "get_weather", "description": "d", "parameters": {"type": "object"}}
    )
    assert decl.name == "get_weather"
    assert decl.description == "d"
    assert decl.parameters == {"type": "object"}


def test_tool_declaration_from_openai_function_dict():
    decl = ToolDeclaration.from_dict(
        {"type": "function", "function": {"name": "f", "description": "d"}}
    )
    assert decl.name == "f"
    assert decl.description == "d"


def test_tool_declaration_requires_name():
    with pytest.raises(ConfigurationError):
        ToolDeclaration.from_dict({"description": "no name"})


def test_tool_result_to_jsonable():
    assert ToolResult(call_id="c1", content="ok").to_jsonable() == {
        "call_id": "c1",
        "content": "ok",
    }
    assert ToolResult(call_id="c1", content="boom", is_error=True).to_jsonable() == {
        "call_id": "c1",
        "content": "boom",
        "is_error": True,
    }
