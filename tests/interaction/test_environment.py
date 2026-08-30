"""Unit tests for public ``Environment`` identity."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import pollux
import pollux.interaction
from pollux.interaction.environment import CachePolicy, Environment
from pollux.interaction.tools import ToolDeclaration
from pollux.source import Source

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_environment_freezes_sequences_to_tuples() -> None:
    env = Environment(
        sources=[Source.from_text("a")],
        tools=[ToolDeclaration(name="f", description="d")],
    )
    assert isinstance(env.sources, tuple)
    assert isinstance(env.tools, tuple)


def test_fingerprint_is_stable_and_normalizes_mapping_order() -> None:
    first = Environment(
        instructions="sys",
        tools=[
            ToolDeclaration(
                name="f",
                parameters={"type": "object", "properties": {"a": {}, "b": {}}},
            )
        ],
    )
    second = Environment(
        instructions="sys",
        tools=[
            ToolDeclaration(
                name="f",
                parameters={"properties": {"b": {}, "a": {}}, "type": "object"},
            )
        ],
    )
    assert first.fingerprint(provider="openai") == second.fingerprint(provider="openai")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (Environment(instructions="a"), Environment(instructions="b")),
        (
            Environment(sources=[Source.from_text("a"), Source.from_text("b")]),
            Environment(sources=[Source.from_text("b"), Source.from_text("a")]),
        ),
        (
            Environment(tools=[ToolDeclaration(name="f", strict=True)]),
            Environment(tools=[ToolDeclaration(name="f", strict=False)]),
        ),
        (
            Environment(
                tools=[ToolDeclaration(name="f", parameters={"type": "object"})]
            ),
            Environment(
                tools=[ToolDeclaration(name="f", parameters={"type": "string"})]
            ),
        ),
    ],
)
def test_fingerprint_changes_with_model_visible_environment(
    first: Environment, second: Environment
) -> None:
    assert first.fingerprint(provider="openai") != second.fingerprint(provider="openai")


def test_fingerprint_changes_with_provider_and_provider_hints() -> None:
    source = Source.from_youtube("https://youtu.be/example").with_gemini_video_settings(
        fps=1
    )
    env = Environment(sources=[source])
    assert env.fingerprint(provider="gemini") != env.fingerprint(provider="openai")


def test_fingerprint_tracks_local_file_content_mime_and_identifier(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first.bin"
    second_path = tmp_path / "second.bin"
    first_path.write_bytes(b"one")
    second_path.write_bytes(b"one")

    original = Environment(sources=[Source.from_file(first_path)])
    different_name = Environment(sources=[Source.from_file(second_path)])
    different_mime = Environment(
        sources=[Source.from_file(first_path, mime_type="text/plain")]
    )
    original_hash = original.fingerprint(provider="anthropic")

    assert original_hash != different_name.fingerprint(provider="anthropic")
    assert original_hash != different_mime.fingerprint(provider="anthropic")

    first_path.write_bytes(b"two")
    assert original_hash != original.fingerprint(provider="anthropic")


def test_uri_fingerprint_is_network_free(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: pytest.fail("fingerprinting performed network I/O"),
    )
    env = Environment(sources=[Source.from_uri("https://example.com/report.pdf")])
    assert env.fingerprint(provider="gemini")


def test_cache_does_not_change_fingerprint() -> None:
    base = Environment(instructions="sys")
    policy = Environment(
        instructions="sys",
        cache=CachePolicy(ttl_seconds=3600),
    )
    assert base.fingerprint(provider="gemini") == policy.fingerprint(provider="gemini")


def test_environment_snapshot_is_not_publicly_exported() -> None:
    assert "EnvironmentSnapshot" not in pollux.__all__
    assert "EnvironmentSnapshot" not in pollux.interaction.__all__
    assert not hasattr(pollux, "EnvironmentSnapshot")
