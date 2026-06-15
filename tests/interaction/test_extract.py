"""Unit tests for ProviderResponse -> Output extraction."""

from __future__ import annotations

from pydantic import BaseModel
import pytest

from pollux.interaction.extract import provider_response_to_output
from pollux.interaction.requirements import OutputRequirements
from pollux.providers.models import ProviderResponse, ToolCall

pytestmark = pytest.mark.unit


class _Answer(BaseModel):
    value: int


def test_maps_response_facets():
    resp = ProviderResponse(
        text="hi",
        usage={"input_tokens": 3, "total_tokens": 8},
        reasoning="because",
        tool_calls=[ToolCall(id="c1", name="f", arguments='{"a": 1}')],
        finish_reason="stop",
    )
    out = provider_response_to_output(
        resp, requirements=OutputRequirements(), duration_s=1.0
    )
    assert out.text == "hi"
    assert out.reasoning == "because"
    assert out.tool_calls[0].name == "f"
    assert out.tool_calls[0].arguments == {"a": 1}
    assert out.usage.input_tokens == 3
    assert out.metrics.finish_reason == "stop"
    assert out.metrics.completion_status == "clean"
    assert out.diagnostics.raw is not None
    assert "response" in out.diagnostics.raw


def test_truncated_completion_status_from_finish_reason():
    resp = ProviderResponse(text="...", usage={}, finish_reason="max_tokens")
    out = provider_response_to_output(
        resp, requirements=OutputRequirements(), duration_s=0.0
    )
    assert out.metrics.completion_status == "truncated"


def test_structured_validates_against_model():
    resp = ProviderResponse(text="", usage={}, structured={"value": 7})
    out = provider_response_to_output(
        resp, requirements=OutputRequirements(output_schema=_Answer), duration_s=0.0
    )
    assert isinstance(out.structured, _Answer)
    assert out.structured.value == 7


def test_structured_from_text_json_fallback():
    resp = ProviderResponse(text='{"value": 9}', usage={})
    out = provider_response_to_output(
        resp, requirements=OutputRequirements(output_schema=_Answer), duration_s=0.0
    )
    assert out.structured.value == 9


def test_no_structured_without_schema():
    resp = ProviderResponse(text='{"value": 1}', usage={})
    out = provider_response_to_output(
        resp, requirements=OutputRequirements(), duration_s=0.0
    )
    assert out.structured is None
