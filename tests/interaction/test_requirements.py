"""Unit tests for ``OutputRequirements`` validation and schema helpers."""

from __future__ import annotations

from pydantic import BaseModel
import pytest

from pollux.errors import ConfigurationError
from pollux.interaction.requirements import OutputRequirements

pytestmark = pytest.mark.unit


class _Answer(BaseModel):
    value: int


def test_accepts_first_class_generation_controls():
    req = OutputRequirements(temperature=0.0, top_p=0.9, max_tokens=512, seed=42)
    assert req.temperature == 0.0
    assert req.max_tokens == 512
    assert req.seed == 42


def test_rejects_non_positive_max_tokens():
    with pytest.raises(ConfigurationError, match="max_tokens"):
        OutputRequirements(max_tokens=0)


def test_rejects_negative_reasoning_budget():
    with pytest.raises(ConfigurationError, match="reasoning_budget_tokens"):
        OutputRequirements(reasoning_budget_tokens=-1)


def test_rejects_reasoning_effort_and_budget_together():
    with pytest.raises(ConfigurationError, match="mutually exclusive"):
        OutputRequirements(reasoning_effort="high", reasoning_budget_tokens=1024)


def test_rejects_unknown_provider_options_provider():
    with pytest.raises(ConfigurationError, match="Unknown provider_options"):
        OutputRequirements(provider_options={"not_a_provider": {"k": "v"}})


def test_provider_options_for_returns_scoped_copy():
    req = OutputRequirements(provider_options={"openai": {"frequency_penalty": 0.5}})
    assert req.provider_options_for("openai") == {"frequency_penalty": 0.5}
    assert req.provider_options_for("anthropic") is None


def test_schema_helpers_for_pydantic_model():
    req = OutputRequirements(output_schema=_Answer)
    assert req.output_schema_model() is _Answer
    schema_json = req.output_schema_json()
    assert schema_json is not None
    assert schema_json["title"] == "_Answer"
    assert req.output_schema_hash() is not None


def test_schema_helpers_none_without_schema():
    req = OutputRequirements()
    assert req.output_schema_model() is None
    assert req.output_schema_json() is None
    assert req.output_schema_hash() is None
