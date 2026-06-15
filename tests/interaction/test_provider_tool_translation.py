"""Coverage: v2 ToolDeclaration dicts translate correctly per provider.

The v2 path compiles tools to a neutral ``{name, description, parameters}`` dict.
These tests confirm each real adapter's tool normalizer consumes that exact shape,
so tool calling is provider-complete through the v2 boundary (not just mock).
"""

from __future__ import annotations

from typing import Any

import pytest

from pollux.config import Config, ProviderName
from pollux.errors import ConfigurationError
from pollux.interaction.environment import Environment, EnvironmentSnapshot
from pollux.interaction.execute import execute_interaction
from pollux.interaction.input import Input
from pollux.interaction.requirements import OutputRequirements
from pollux.interaction.tools import ToolDeclaration
from pollux.providers import _compile
from pollux.providers.anthropic import AnthropicProvider
from pollux.providers.local import LocalProvider
from pollux.providers.openai import OpenAIProvider

pytestmark = pytest.mark.unit

_LOCAL_BASE_URL = "http://localhost:1234/v1"
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


@pytest.mark.asyncio
async def test_local_rejects_tools_through_v2():
    provider = LocalProvider(base_url=_LOCAL_BASE_URL)
    cfg = Config(provider="local", model="m", base_url=_LOCAL_BASE_URL)
    with pytest.raises(ConfigurationError):
        await execute_interaction(
            Environment(tools=[_TOOL]),
            Input(content="hi"),
            OutputRequirements(),
            cfg,
            provider,
        )
