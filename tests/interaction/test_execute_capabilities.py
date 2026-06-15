"""Integration tests: Config capability declarations steer v2 validation."""

from __future__ import annotations

from pydantic import BaseModel
import pytest

from pollux.config import Config
from pollux.errors import ConfigurationError
from pollux.interaction.environment import Environment
from pollux.interaction.execute import execute_interaction
from pollux.interaction.input import Input
from pollux.interaction.requirements import OutputRequirements
from pollux.providers.base import ProviderCapabilities
from tests.conftest import ANTHROPIC_MODEL, FakeProvider

pytestmark = pytest.mark.integration


class _Out(BaseModel):
    value: int


@pytest.mark.asyncio
async def test_declaration_caps_provider_support():
    # Provider statically supports structured outputs; Config caps it off.
    provider = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True, uploads=True, structured_outputs=True
        )
    )
    cfg = Config(
        provider="anthropic",
        model=ANTHROPIC_MODEL,
        use_mock=True,
        capabilities={"structured_outputs": False},
    )
    with pytest.raises(ConfigurationError, match="structured outputs"):
        await execute_interaction(
            Environment(),
            Input(content="Q"),
            OutputRequirements(output_schema=_Out),
            cfg,
            provider,
        )


@pytest.mark.asyncio
async def test_declaration_asserts_support_provider_omits():
    # Provider static block omits structured outputs; Config asserts it.
    provider = FakeProvider()  # structured_outputs=False by default
    cfg = Config(
        provider="anthropic",
        model=ANTHROPIC_MODEL,
        use_mock=True,
        capabilities={"structured_outputs": True},
    )
    out = await execute_interaction(
        Environment(),
        Input(content="Q"),
        OutputRequirements(output_schema=_Out),
        cfg,
        provider,
    )
    assert out.text == "ok:Q"


@pytest.mark.asyncio
async def test_unknown_capability_declaration_raises_before_call():
    provider = FakeProvider()
    cfg = Config(
        provider="anthropic",
        model=ANTHROPIC_MODEL,
        use_mock=True,
        capabilities={"telepathy": True},
    )
    with pytest.raises(ConfigurationError, match="Unknown capability"):
        await execute_interaction(
            Environment(), Input(content="Q"), OutputRequirements(), cfg, provider
        )
