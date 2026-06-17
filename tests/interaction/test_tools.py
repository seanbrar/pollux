"""Unit tests for the v2 tool primitives."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from pollux.errors import ConfigurationError, ToolCallParseError
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


def test_tool_call_arguments_dict_returns_parsed_object():
    call = ToolCall.from_text(id="c1", name="f", arguments_text='{"city": "Paris"}')
    assert call.arguments_dict() == {"city": "Paris"}


def test_tool_call_arguments_dict_treats_empty_arguments_as_empty_object():
    call = ToolCall.from_text(id="c1", name="f")
    assert call.arguments_dict() == {}


def test_tool_call_arguments_dict_rejects_invalid_json():
    call = ToolCall.from_text(id="c1", name="f", arguments_text="{not json")
    with pytest.raises(ToolCallParseError, match="invalid JSON arguments") as exc:
        call.arguments_dict()
    assert exc.value.error_category == "tool_call_parse"
    assert exc.value.tool_call_id == "c1"
    assert exc.value.arguments_text == "{not json"


def test_tool_call_arguments_dict_rejects_non_object_json():
    call = ToolCall.from_text(id="c1", name="f", arguments_text='["not", "object"]')
    with pytest.raises(ToolCallParseError, match="must be a JSON object"):
        call.arguments_dict()


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


def test_tool_result_from_value_preserves_strings():
    assert ToolResult.from_value(call_id="c1", value="ok").content == "ok"


def test_tool_result_from_value_serializes_json_values():
    result = ToolResult.from_value(
        call_id="c1",
        value={"temp_f": 72, "conditions": ["sunny"]},
    )
    assert result.content == '{"conditions": ["sunny"], "temp_f": 72}'


def test_tool_result_from_value_marks_errors():
    result = ToolResult.from_value(call_id="c1", value={"error": "boom"}, is_error=True)
    assert result.is_error is True
    assert result.to_jsonable()["is_error"] is True
