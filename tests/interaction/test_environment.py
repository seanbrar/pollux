"""Unit tests for ``Environment`` and ``EnvironmentSnapshot``."""

from __future__ import annotations

import pytest

from pollux.interaction.environment import (
    CachePolicy,
    Environment,
    EnvironmentSnapshot,
)
from pollux.interaction.tools import ToolDeclaration
from pollux.source import Source

pytestmark = pytest.mark.unit


def test_environment_freezes_sequences_to_tuples():
    env = Environment(
        sources=[Source.from_text("a")],
        tools=[ToolDeclaration(name="f", description="d")],
    )
    assert isinstance(env.sources, tuple)
    assert isinstance(env.tools, tuple)
    assert env.tools[0].name == "f"


def test_environment_accepts_declaration_objects():
    decl = ToolDeclaration(name="f", description="d")
    env = Environment(tools=[decl])
    assert env.tools[0] is decl


def test_snapshot_fingerprint_is_stable():
    env = Environment(instructions="sys", sources=(Source.from_text("doc"),))
    snap_a = EnvironmentSnapshot.from_environment(env)
    snap_b = EnvironmentSnapshot.from_environment(env)
    assert snap_a.fingerprint() == snap_b.fingerprint()


def test_snapshot_fingerprint_changes_with_instructions():
    base = EnvironmentSnapshot.from_environment(Environment(instructions="a"))
    other = EnvironmentSnapshot.from_environment(Environment(instructions="b"))
    assert base.fingerprint() != other.fingerprint()


def test_snapshot_fingerprint_changes_with_sources():
    one = EnvironmentSnapshot.from_environment(
        Environment(sources=(Source.from_text("x"),))
    )
    two = EnvironmentSnapshot.from_environment(
        Environment(sources=(Source.from_text("y"),))
    )
    assert one.fingerprint() != two.fingerprint()


def test_snapshot_fingerprint_changes_with_cache_policy():
    none_cache = EnvironmentSnapshot.from_environment(Environment())
    ttl_cache = EnvironmentSnapshot.from_environment(
        Environment(cache=CachePolicy(ttl_seconds=3600))
    )
    assert none_cache.fingerprint() != ttl_cache.fingerprint()
