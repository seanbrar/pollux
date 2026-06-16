"""Integration tests: the runtime continuation-compatibility contract.

A live ``Continuation`` records the provider that produced it. Reusing it under a
different provider is rejected before dispatch, because its ``provider_state``
(response ids, provider-specific replay blocks) is not portable.
"""

from __future__ import annotations

import pytest

from pollux.config import Config
from pollux.errors import ConfigurationError
from pollux.interaction.continuation import Continuation, Message
from pollux.interaction.environment import Environment
from pollux.interaction.execute import execute_interaction
from pollux.interaction.input import Input
from pollux.interaction.requirements import OutputRequirements
from pollux.providers.base import ProviderCapabilities
from tests.conftest import ANTHROPIC_MODEL, FakeProvider

pytestmark = pytest.mark.integration


def _conversational_provider() -> FakeProvider:
    return FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True, uploads=True, conversation=True
        )
    )


def _cfg() -> Config:
    return Config(provider="anthropic", model=ANTHROPIC_MODEL, use_mock=True)


def _continuation(provider: str | None) -> Continuation:
    return Continuation(
        messages=(Message(role="user", content="earlier"),),
        provider=provider,
    )


@pytest.mark.asyncio
async def test_rejects_continuation_from_a_different_provider() -> None:
    with pytest.raises(ConfigurationError, match="active provider"):
        await execute_interaction(
            Environment(),
            Input(content="next", continuation=_continuation("openai")),
            OutputRequirements(),
            _cfg(),
            _conversational_provider(),
        )


@pytest.mark.asyncio
async def test_accepts_continuation_from_the_matching_provider() -> None:
    out = await execute_interaction(
        Environment(),
        Input(content="next", continuation=_continuation("anthropic")),
        OutputRequirements(),
        _cfg(),
        _conversational_provider(),
    )
    assert out.text == "ok:next"


@pytest.mark.asyncio
async def test_accepts_continuation_without_a_provider_marker() -> None:
    # Hand-built or history-derived continuations carry no provider marker and
    # are left alone by the compatibility check.
    out = await execute_interaction(
        Environment(),
        Input(content="next", continuation=_continuation(None)),
        OutputRequirements(),
        _cfg(),
        _conversational_provider(),
    )
    assert out.text == "ok:next"
