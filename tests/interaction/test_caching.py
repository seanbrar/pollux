"""Persistent caching over the v2 interaction path.

These cover the 3b-2 wiring: an ``Environment`` carrying a ``CachePolicy`` makes
the execution path create (or reuse) a provider-side cache, bake the stable
context into it, and reflect that on ``Output`` metrics. ``prepare_environment``
front-loads that work; ``run``/``run_many`` accept the prepared environment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import pollux
from pollux.cache import _registry
from pollux.config import Config
from pollux.errors import ConfigurationError
from pollux.interaction.environment import CachePolicy, Environment
from pollux.providers.base import ProviderCapabilities
from pollux.source import Source
from tests.conftest import GEMINI_MODEL, FakeProvider

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _reset_cache_registry() -> Iterator[None]:
    """Isolate the module-level cache registry between tests."""
    _registry._entries.clear()
    _registry._inflight.clear()
    yield
    _registry._entries.clear()
    _registry._inflight.clear()


def _cfg() -> Config:
    return Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)


@pytest.mark.asyncio
async def test_persistent_cache_created_once_for_fan_out(monkeypatch):
    """A CachePolicy environment creates one cache and reuses it across prompts."""
    provider = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    environment = Environment(
        sources=[Source.from_text("SHARED CONTEXT")],
        cache=CachePolicy(ttl_seconds=600),
    )
    coll = await pollux.run_many(
        ["Q1", "Q2", "Q3"], environment=environment, config=_cfg()
    )

    assert provider.cache_calls == 1
    assert coll.answers == ["ok:Q1", "ok:Q2", "ok:Q3"]
    assert all(o.metrics.cache_mode == "persistent" for o in coll.outputs)
    assert all(o.metrics.cache_used for o in coll.outputs)
    assert all(o.metrics.cache_hit for o in coll.outputs)


@pytest.mark.asyncio
async def test_cached_sources_not_resent_in_request(monkeypatch):
    """When a cache is in use, sources are baked in, not resent as parts."""
    provider = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    environment = Environment(
        sources=[Source.from_text("SHARED CONTEXT")],
        cache=CachePolicy(ttl_seconds=600),
    )
    await pollux.run("Q1", environment=environment, config=_cfg())

    assert provider.last_parts == ["Q1"]
    assert "SHARED CONTEXT" not in (provider.last_parts or [])


@pytest.mark.asyncio
async def test_cache_suppresses_instructions_and_tools_on_request(monkeypatch):
    """Instructions and tools live in the cache, so they are not resent."""
    provider = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    environment = Environment(
        instructions="Be terse.",
        sources=[Source.from_text("SHARED CONTEXT")],
        tools=[
            pollux.ToolDeclaration(
                name="lookup", description="d", parameters={"type": "object"}
            )
        ],
        cache=CachePolicy(ttl_seconds=600),
    )
    await pollux.run("Q1", environment=environment, config=_cfg())

    assert provider.last_generate_kwargs is not None
    assert provider.last_generate_kwargs["system_instruction"] is None
    assert provider.last_generate_kwargs["tools"] is None


@pytest.mark.asyncio
async def test_persistent_cache_reused_across_separate_calls(monkeypatch):
    """A cache created once is reused by identity across later calls."""
    provider = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    environment = Environment(
        sources=[Source.from_text("SHARED CONTEXT")],
        cache=CachePolicy(ttl_seconds=600),
    )
    await pollux.run("Q1", environment=environment, config=_cfg())
    await pollux.run("Q2", environment=environment, config=_cfg())

    assert provider.cache_calls == 1


@pytest.mark.asyncio
async def test_prepare_environment_creates_cache_eagerly(monkeypatch):
    """prepare_environment front-loads cache creation; later runs reuse it."""
    provider = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    environment = await pollux.prepare_environment(
        sources=[Source.from_text("SHARED CONTEXT")],
        cache=CachePolicy(ttl_seconds=600),
        config=_cfg(),
    )
    assert provider.cache_calls == 1

    await pollux.run_many(["Q1", "Q2"], environment=environment, config=_cfg())
    assert provider.cache_calls == 1


@pytest.mark.asyncio
async def test_prepare_environment_does_no_io_without_policy(monkeypatch):
    """Without a CachePolicy, prepare_environment is a pure constructor."""
    provider = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    environment = await pollux.prepare_environment(
        sources=[Source.from_text("SHARED CONTEXT")],
        cache="auto",
        config=_cfg(),
    )
    assert provider.cache_calls == 0
    assert environment.cache == "auto"


@pytest.mark.asyncio
async def test_persistent_cache_rejected_when_unsupported(monkeypatch):
    """A CachePolicy against a provider without persistent_cache fails clearly."""
    provider = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=False, uploads=True, structured_outputs=False
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    environment = Environment(
        sources=[Source.from_text("SHARED CONTEXT")],
        cache=CachePolicy(ttl_seconds=600),
    )
    with pytest.raises(ConfigurationError, match="persistent caching"):
        await pollux.run("Q1", environment=environment, config=_cfg())
    assert provider.cache_calls == 0


@pytest.mark.asyncio
async def test_cache_none_disables_implicit_caching(monkeypatch):
    """cache='none' opts out of provider-managed caching too."""
    provider = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=False, uploads=True, implicit_caching=True
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    environment = Environment(cache="none")
    out = await pollux.run("Q1", environment=environment, config=_cfg())
    assert out.metrics.cache_mode == "none"


@pytest.mark.asyncio
async def test_run_many_rejects_environment_with_inline_kwargs(monkeypatch):
    """Mixing a prepared environment with inline setup is a configuration error."""
    provider = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    environment = Environment(sources=[Source.from_text("CTX")])
    with pytest.raises(ConfigurationError, match="environment cannot be combined"):
        await pollux.run_many(
            ["Q1"], environment=environment, instructions="sys", config=_cfg()
        )


@pytest.mark.asyncio
async def test_run_rejects_environment_with_inline_source(monkeypatch):
    """run() also guards against environment + inline source."""
    provider = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: provider)

    environment = Environment(sources=[Source.from_text("CTX")])
    with pytest.raises(ConfigurationError, match="environment cannot be combined"):
        await pollux.run(
            "Q1",
            environment=environment,
            source=Source.from_text("OTHER"),
            config=_cfg(),
        )
