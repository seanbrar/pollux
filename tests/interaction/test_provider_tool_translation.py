"""Coverage: v2 ToolDeclaration dicts translate correctly per provider.

The v2 path compiles tools to a neutral ``{name, description, parameters}`` dict.
These tests confirm each real adapter's tool normalizer consumes that exact shape,
so tool calling is provider-complete through the v2 boundary (not just mock).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from pollux.interaction.environment import Environment, EnvironmentSnapshot
from pollux.interaction.tools import ToolDeclaration
from pollux.providers import _compile
from pollux.providers._openai_compat import normalize_tools
from pollux.providers.anthropic import AnthropicProvider
from pollux.providers.openai import OpenAIProvider

if TYPE_CHECKING:
    from pollux.config import ProviderName

pytestmark = pytest.mark.unit

_TOOL = ToolDeclaration(
    name="get_weather",
    description="Get weather",
    parameters={"type": "object", "properties": {"city": {"type": "string"}}},
)


def _compiled_tools(provider_name: ProviderName) -> list[dict[str, Any]]:
    snapshot = EnvironmentSnapshot.from_environment(
        Environment(tools=[_TOOL]), provider=provider_name
    )
    tools = _compile.tool_dicts(snapshot)
    assert tools is not None
    return tools


def test_translates_to_anthropic_input_schema():
    tools = AnthropicProvider._normalize_tools(_compiled_tools("anthropic"))
    assert tools[0]["name"] == "get_weather"
    assert tools[0]["input_schema"]["type"] == "object"
    assert tools[0]["description"] == "Get weather"


def test_translates_to_openai_function():
    tools = OpenAIProvider._normalize_tools(_compiled_tools("openai"))
    assert tools[0]["type"] == "function"
    assert tools[0]["name"] == "get_weather"
    assert "parameters" in tools[0]


def test_translates_to_local_function():
    tools = normalize_tools(_compiled_tools("local"))
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "get_weather"
    assert "parameters" in tools[0]["function"]
