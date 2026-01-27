"""Property-based tests for configuration precedence.

These tests verify that the precedence rule "Programmatic > Env > Project > Home > Defaults"
is consistently applied across all configuration fields.
"""

import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from pollux.config import Origin, resolve_config

pytestmark = pytest.mark.unit


class TestConfigPrecedenceProperties:
    """Property-based tests for configuration precedence rules."""

    def test_programmatic_overrides_win_over_all_sources(self):
        """Programmatic overrides should take precedence over all other sources."""
        # Setup: create environment and file sources
        env_vars = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")}
        env_vars.update(
            {
                "POLLUX_MODEL": "env-model",
                "POLLUX_TTL_SECONDS": "1200",
                "POLLUX_USE_REAL_API": "true",
            }
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("""
[tool.pollux]
model = "file-model"
ttl_seconds = 2400
enable_caching = true
""")
            temp_file = Path(f.name)

        try:
            with (
                patch.dict(
                    os.environ,
                    {**env_vars, "POLLUX_PYPROJECT_PATH": str(temp_file)},
                    clear=True,
                ),
                patch("pollux.config.loaders.load_home", return_value={}),
                patch(
                    "pollux.config.loaders.load_env",
                    return_value={
                        "model": "env-model",
                        "ttl_seconds": 1200,
                        "use_real_api": True,
                    },
                ),
            ):
                try:
                    # Test: Programmatic overrides should win
                    config, sources = resolve_config(
                        overrides={
                            "model": "override-model",
                            "ttl_seconds": 3600,
                            "use_real_api": False,
                        },
                        explain=True,
                    )

                    # Assert: Programmatic values win
                    assert config.model == "override-model"
                    assert config.ttl_seconds == 3600
                    assert config.use_real_api is False
                    assert config.enable_caching is True  # From file (not overridden)

                    # Assert: Sources are correctly tracked
                    assert sources["model"].origin == Origin.OVERRIDES
                    assert sources["ttl_seconds"].origin == Origin.OVERRIDES
                    assert sources["use_real_api"].origin == Origin.OVERRIDES
                    assert sources["enable_caching"].origin == Origin.PROJECT

                finally:
                    temp_file.unlink(missing_ok=True)
        finally:
            if temp_file.exists():
                temp_file.unlink()

    def test_env_wins_over_file_and_defaults(self):
        """Environment variables should override file and default values."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("""
[tool.pollux]
model = "file-model"
ttl_seconds = 1800
enable_caching = false
""")
            temp_file = Path(f.name)

        try:
            env_vars = {
                k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")
            }
            env_vars.update(
                {
                    "POLLUX_MODEL": "env-model",
                    "POLLUX_ENABLE_CACHING": "true",  # Override file value
                    # ttl_seconds not set in env - should use file value
                }
            )

            with (
                patch.dict(
                    os.environ,
                    {**env_vars, "POLLUX_PYPROJECT_PATH": str(temp_file)},
                    clear=True,
                ),
                patch("pollux.config.loaders.load_home", return_value={}),
                patch(
                    "pollux.config.loaders.load_env",
                    return_value={"model": "env-model", "enable_caching": True},
                ),
            ):
                try:
                    config, sources = resolve_config(explain=True)

                    # Assert: Env wins over file
                    assert config.model == "env-model"
                    assert config.enable_caching is True
                    # Assert: File wins where env is not set
                    assert config.ttl_seconds == 1800

                    # Assert: Sources are correctly tracked
                    assert sources["model"].origin == Origin.ENV
                    assert sources["enable_caching"].origin == Origin.ENV
                    assert sources["ttl_seconds"].origin == Origin.PROJECT

                finally:
                    temp_file.unlink(missing_ok=True)
        finally:
            if temp_file.exists():
                temp_file.unlink()

    def test_project_wins_over_home_and_defaults(self):
        """Project config should override home config and defaults."""
        # Create both home and project config files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Project config
            project_file = temp_path / "pyproject.toml"
            project_file.write_text("""
[tool.pollux]
model = "project-model"
ttl_seconds = 1800
""")

            # Home config
            home_file = temp_path / "home_config.toml"
            home_file.write_text("""
[tool.pollux]
model = "home-model"
ttl_seconds = 2400
enable_caching = true
""")

            clean_env = {
                k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")
            }
            with (
                patch.dict(
                    os.environ,
                    {
                        **clean_env,
                        "POLLUX_PYPROJECT_PATH": str(project_file),
                        "POLLUX_CONFIG_HOME": str(home_file),
                    },
                    clear=True,
                ),
                patch("pollux.config.loaders.load_env", return_value={}),
                patch(
                    "pollux.config.loaders.load_home",
                    return_value={
                        "model": "home-model",
                        "ttl_seconds": 2400,
                        "enable_caching": True,
                    },
                ),
            ):
                config, sources = resolve_config(explain=True)

                # Assert: Project wins over home
                assert config.model == "project-model"
                assert config.ttl_seconds == 1800
                # Assert: Home value used where project doesn't specify
                assert config.enable_caching is True

                # Assert: Sources are correctly tracked
                assert sources["model"].origin == Origin.PROJECT
                assert sources["ttl_seconds"].origin == Origin.PROJECT
                assert sources["enable_caching"].origin == Origin.HOME

    def test_precedence_per_field_independence(self):
        """Each field should follow precedence independently of other fields."""
        env_vars = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")}
        env_vars.update(
            {
                "POLLUX_MODEL": "env-model",
                # Note: ttl_seconds NOT set in env
            }
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("""
[tool.pollux]
ttl_seconds = 1800
enable_caching = true
# Note: model NOT set in file
""")
            temp_file = Path(f.name)

        try:
            with (
                patch.dict(
                    os.environ,
                    {**env_vars, "POLLUX_PYPROJECT_PATH": str(temp_file)},
                    clear=True,
                ),
                patch("pollux.config.loaders.load_home", return_value={}),
                patch(
                    "pollux.config.loaders.load_env",
                    return_value={"model": "env-model"},
                ),
            ):
                try:
                    config, sources = resolve_config(
                        overrides={"use_real_api": False},  # Only one override
                        explain=True,
                    )

                    # Assert: Each field uses its highest-precedence source
                    assert config.use_real_api is False  # From overrides
                    assert config.model == "env-model"  # From env
                    assert config.ttl_seconds == 1800  # From project file
                    assert config.enable_caching is True  # From project file
                    assert config.api_key is None  # From defaults

                    # Assert: Sources correctly reflect actual origins
                    assert sources["use_real_api"].origin == Origin.OVERRIDES
                    assert sources["model"].origin == Origin.ENV
                    assert sources["ttl_seconds"].origin == Origin.PROJECT
                    assert sources["enable_caching"].origin == Origin.PROJECT
                    assert sources["api_key"].origin == Origin.DEFAULT

                finally:
                    temp_file.unlink(missing_ok=True)
        finally:
            if temp_file.exists():
                temp_file.unlink()

    def test_profile_precedence_within_layers(self):
        """Profiles should correctly overlay within each layer."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("""
[tool.pollux]
model = "base-model"
ttl_seconds = 1800

[tool.pollux.profiles.test]
model = "test-model"
# ttl_seconds not overridden - should use base value
enable_caching = true
""")
            temp_file = Path(f.name)

        try:
            clean_env = {
                k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")
            }
            clean_env["POLLUX_USE_REAL_API"] = (
                "true"  # Env should still win over profile
            )

            with (
                patch.dict(
                    os.environ,
                    {**clean_env, "POLLUX_PYPROJECT_PATH": str(temp_file)},
                    clear=True,
                ),
                patch("pollux.config.loaders.load_home", return_value={}),
                patch(
                    "pollux.config.loaders.load_env",
                    return_value={"use_real_api": False},
                ),
            ):
                try:
                    config, sources = resolve_config(profile="test", explain=True)

                    # Assert: Profile values override base within the same layer
                    assert config.model == "test-model"  # Profile override
                    assert config.ttl_seconds == 1800  # Base value (not in profile)
                    assert config.enable_caching is True  # Profile value
                    assert (
                        config.use_real_api is False
                    )  # Env still wins over project+profile

                    # Assert: All project values attributed to PROJECT layer
                    assert sources["model"].origin == Origin.PROJECT
                    assert sources["ttl_seconds"].origin == Origin.PROJECT
                    assert sources["enable_caching"].origin == Origin.PROJECT
                    assert sources["use_real_api"].origin == Origin.ENV

                finally:
                    temp_file.unlink(missing_ok=True)
        finally:
            if temp_file.exists():
                temp_file.unlink()
