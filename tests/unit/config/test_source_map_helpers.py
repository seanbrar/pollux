"""Tests for simple SourceMap provenance helpers.

These tests validate that tiny, generic helpers can detect whether a field
was supplied by user-provided sources (env/file/overrides) versus defaults.
"""

from unittest.mock import patch

import pytest

from pollux.config import resolve_config, tier_was_specified

pytestmark = pytest.mark.unit


def test_tier_was_specified_is_false_when_default_only():
    """When no sources provide 'tier', helper should return False."""
    with (
        patch("pollux.config.loaders.load_env", return_value={}),
        patch("pollux.config.loaders.load_pyproject", return_value={}),
        patch("pollux.config.loaders.load_home", return_value={}),
    ):
        _, sources = resolve_config(explain=True)
        assert tier_was_specified(sources) is False


def test_tier_was_specified_true_for_overrides():
    """Overrides should mark 'tier' as specified."""
    with (
        patch("pollux.config.loaders.load_env", return_value={}),
        patch("pollux.config.loaders.load_pyproject", return_value={}),
        patch("pollux.config.loaders.load_home", return_value={}),
    ):
        _, sources = resolve_config(overrides={"tier": "TIER_1"}, explain=True)
        assert tier_was_specified(sources) is True


def test_tier_was_specified_true_for_env():
    """Environment should mark 'tier' as specified."""
    with (
        patch("pollux.config.loaders.load_env", return_value={"tier": "TIER_1"}),
        patch("pollux.config.loaders.load_pyproject", return_value={}),
        patch("pollux.config.loaders.load_home", return_value={}),
    ):
        _, sources = resolve_config(explain=True)
        assert tier_was_specified(sources) is True


def test_tier_was_specified_true_for_project():
    """Project file should mark 'tier' as specified."""
    with (
        patch("pollux.config.loaders.load_env", return_value={}),
        patch(
            "pollux.config.loaders.load_pyproject",
            return_value={"tier": "TIER_1"},
        ),
        patch("pollux.config.loaders.load_home", return_value={}),
    ):
        _, sources = resolve_config(explain=True)
        assert tier_was_specified(sources) is True


def test_tier_was_specified_true_for_home():
    """Home file should mark 'tier' as specified."""
    with (
        patch("pollux.config.loaders.load_env", return_value={}),
        patch("pollux.config.loaders.load_pyproject", return_value={}),
        patch("pollux.config.loaders.load_home", return_value={"tier": "TIER_1"}),
    ):
        _, sources = resolve_config(explain=True)
        assert tier_was_specified(sources) is True
