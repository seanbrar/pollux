"""Architectural invariant tests for the configuration system."""

import os
from unittest.mock import patch

import pytest

from pollux.config import resolve_config


@pytest.mark.contract
def test_precedence_order_invariant() -> None:
    """Invariant: Precedence order must be overrides > env > project > home > defaults."""
    from pathlib import Path
    import tempfile

    from pollux.config import Origin

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        project_file = temp_path / "pyproject.toml"
        project_file.write_text(
            '[tool.pollux]\nmodel = "project-model"\nttl_seconds = 100'
        )

        home_file = temp_path / "home_config.toml"
        home_file.write_text(
            '[tool.pollux]\nmodel = "home-model"\nttl_seconds = 200\nenable_caching = true'
        )

        env_vars = {
            "GEMINI_API_KEY": "env_key",
            "POLLUX_MODEL": "env-model",
            "POLLUX_PYPROJECT_PATH": str(project_file),
            "POLLUX_CONFIG_HOME": str(home_file),
        }

        with (
            patch.dict(os.environ, env_vars, clear=True),
            patch(
                "pollux.config.loaders.load_home",
                return_value={
                    "model": "home-model",
                    "ttl_seconds": 200,
                    "enable_caching": True,
                },
            ),
            patch(
                "pollux.config.loaders.load_env",
                return_value={"model": "env-model", "api_key": "env_key"},
            ),
        ):
            result, sources = resolve_config(
                overrides={"api_key": "prog_key"}, explain=True
            )

            assert result.api_key == "prog_key"
            assert sources["api_key"].origin == Origin.OVERRIDES
            assert result.model == "env-model"
            assert sources["model"].origin == Origin.ENV
            assert result.ttl_seconds == 100
            assert sources["ttl_seconds"].origin == Origin.PROJECT
            assert result.enable_caching is True
            assert sources["enable_caching"].origin == Origin.HOME
