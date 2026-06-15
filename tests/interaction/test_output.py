"""Unit tests for ``Output`` and its facets."""

from __future__ import annotations

import pytest

from pollux.interaction.output import (
    Metrics,
    Output,
    Usage,
    completion_status,
)
from pollux.interaction.tools import ToolCall

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("finish_reason", "error_category", "expected"),
    [
        ("stop", None, "clean"),
        ("tool_calls", None, "clean"),
        ("end_turn", None, "clean"),
        (None, None, "clean"),
        ("max_tokens", None, "truncated"),
        ("length", None, "truncated"),
        ("content_filter", None, "cutoff"),
        ("safety", None, "cutoff"),
        ("stop", "context_overflow", "truncated"),
        ("stop", "rate_limit", "error"),
        ("weird_unknown", None, "cutoff"),
    ],
)
def test_completion_status_mapping(finish_reason, error_category, expected):
    assert completion_status(finish_reason, error_category=error_category) == expected


def test_usage_from_dict_ignores_unknown_keys():
    usage = Usage.from_dict(
        {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8, "extra": 1}
    )
    assert usage.input_tokens == 3
    assert usage.output_tokens == 5
    assert usage.total_tokens == 8
    assert usage.reasoning_tokens is None


def test_usage_to_jsonable_omits_unset_optional_facets():
    assert Usage(input_tokens=1, output_tokens=2, total_tokens=3).to_jsonable() == {
        "input_tokens": 1,
        "output_tokens": 2,
        "total_tokens": 3,
    }


def test_output_to_jsonable_has_named_facets_without_v1_vestiges():
    output = Output(
        text="hi",
        tool_calls=(ToolCall.from_text(id="c1", name="f", arguments_text="{}"),),
        metrics=Metrics(finish_reason="stop", completion_status="clean"),
    )
    payload = output.to_jsonable()
    assert payload["text"] == "hi"
    assert payload["tool_calls"][0]["name"] == "f"
    assert payload["metrics"]["completion_status"] == "clean"
    assert "confidence" not in payload
    assert "status" not in payload
    assert "extraction_method" not in payload


def test_output_omits_empty_optional_facets():
    payload = Output(text="hi").to_jsonable()
    assert "structured" not in payload
    assert "reasoning" not in payload
    assert "tool_calls" not in payload
    assert "continuation" not in payload
    assert "diagnostics" not in payload
