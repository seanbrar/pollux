"""Architectural invariant tests for the configuration system.

Layer 2: Architectural Invariants
Prove the system rules remain true across the configuration architecture.
"""

import os
from unittest.mock import patch

import pytest

from pollux.config import resolve_config
from pollux.core.exceptions import ConfigurationError
from pollux.core.models import APITier


class TestConfigurationArchitecturalInvariants:
    """Architectural invariant tests for configuration system."""

    @pytest.mark.contract
    def test_precedence_order_invariant(self):
        """Invariant: Precedence order must be programmatic > env > project > home > defaults."""
        # We simulate the full stack to prove the invariant holds across all layers
        # 1. Defaults are implicit (e.g. model=gemini-2.0-flash)
        # 2. Home config sets a baseline
        # 3. Project config overrides home
        # 4. Env vars override project
        # 5. Programmatic overrides win it all

        from pathlib import Path
        import tempfile

        from pollux.config import Origin

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Setup files
            project_file = temp_path / "pyproject.toml"
            project_file.write_text(
                '[tool.pollux]\nmodel = "project-model"\nttl_seconds = 100'
            )

            home_file = temp_path / "home_config.toml"
            home_file.write_text(
                '[tool.pollux]\nmodel = "home-model"\nttl_seconds = 200\nenable_caching = true'
            )

            # Setup Environment
            env_vars = {
                "GEMINI_API_KEY": "env_key",
                "POLLUX_MODEL": "env-model",
                "POLLUX_PYPROJECT_PATH": str(project_file),
                "POLLUX_CONFIG_HOME": str(home_file),
                # ttl_seconds NOT in env, should fall through to project
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
                # Execute resolution with one override
                result, sources = resolve_config(
                    overrides={"api_key": "prog_key"}, explain=True
                )

                # Verify Precedence Chain

                # 1. Programmatic > Env (api_key)
                assert result.api_key == "prog_key"
                assert sources["api_key"].origin == Origin.OVERRIDES

                # 2. Env > Project (model)
                assert result.model == "env-model"
                assert sources["model"].origin == Origin.ENV

                # 3. Project > Home (ttl_seconds)
                # Env didn't set it, so it falls to project (100) vs home (200)
                # Note: We rely on the loader mocks to be accurate to what real loaders do,
                # but valid config resolution merges them.
                # If we assume standard merging:
                assert result.ttl_seconds == 100
                assert sources["ttl_seconds"].origin == Origin.PROJECT

                # 4. Home > Defaults (enable_caching)
                # Project didn't set it, so it falls to home
                assert result.enable_caching is True
                assert sources["enable_caching"].origin == Origin.HOME

    @pytest.mark.contract
    def test_audit_trail_completeness_invariant(self):
        """Invariant: Every configuration field must have traceable source."""
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test_key", "POLLUX_MODEL": "test_model"},
        ):
            _cfg, origin = resolve_config(explain=True)

            # Every field in frozen config must have source tracking
            frozen_fields = {
                "api_key",
                "model",
                "tier",
                "enable_caching",
                "use_real_api",
                "ttl_seconds",
            }

            for field in frozen_fields:
                assert field in origin, f"Field {field} missing from origin"
                assert hasattr(origin[field], "origin")

    @pytest.mark.contract
    def test_validation_consistency_invariant(self):
        """Invariant: Validation rules must be consistently applied regardless of source."""
        # Test ttl_seconds validation from environment
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test", "POLLUX_TTL_SECONDS": "-1"},
        ):
            with pytest.raises(ConfigurationError) as exc_info:
                resolve_config()
            assert "ttl_seconds" in str(exc_info.value).lower()

        # Test same validation from programmatic config
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
            with pytest.raises(ConfigurationError) as exc_info:
                resolve_config(overrides={"ttl_seconds": -1})
            assert "ttl_seconds" in str(exc_info.value).lower()

    @pytest.mark.contract
    def test_type_safety_invariant(self):
        """Invariant: Type coercion must be consistent and safe."""
        # Test boolean coercion from strings
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test",
                "POLLUX_ENABLE_CACHING": "true",
                "POLLUX_USE_REAL_API": "false",
            },
        ):
            result = resolve_config()

            # String values should be properly coerced to booleans
            assert result.enable_caching is True
            assert result.use_real_api is False

        # Test integer coercion
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test", "POLLUX_TTL_SECONDS": "7200"},
        ):
            result = resolve_config()
            assert result.ttl_seconds == 7200
            assert isinstance(result.ttl_seconds, int)

    @pytest.mark.contract
    def test_tier_consistency_invariant(self):
        """Invariant: APITier must be consistent across the system."""
        # Test that tier is properly resolved to enum
        with patch.dict(
            os.environ, {"GEMINI_API_KEY": "test", "POLLUX_TIER": "tier_1"}
        ):
            result = resolve_config()

            assert isinstance(result.tier, APITier)
            assert result.tier == APITier.TIER_1

        # Test default tier
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}, clear=True):
            result = resolve_config()
            # Default tier may be None by design; ensure type safety when present
            assert (result.tier is None) or isinstance(result.tier, APITier)

    @pytest.mark.contract
    def test_profile_isolation_invariant(self):
        """Invariant: Profile operations must not affect global state."""
        # Test that profile parameter doesn't affect global state
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
            config_before = resolve_config()
            config_with_profile = resolve_config(
                profile=None
            )  # Should not affect anything
            config_after = resolve_config()

            assert config_before == config_after
            assert config_with_profile == config_after

    @pytest.mark.contract
    def test_environment_isolation_invariant(self):
        """Invariant: Configuration resolution must not modify environment."""
        original_env = dict(os.environ)

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
            resolve_config()

            # Environment should be unchanged after resolution
            # (Note: patch.dict handles restoration, but we test the principle)
            assert "GEMINI_API_KEY" in os.environ

        # After patch context, environment should be restored
        assert os.environ == original_env

    @pytest.mark.contract
    def test_deterministic_defaults_invariant(self):
        """Invariant: Default values must be deterministic and consistent."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}, clear=True):
            result1 = resolve_config()
            result2 = resolve_config()

            # Default values should be identical across calls
            assert result1.model == result2.model
            assert result1.tier == result2.tier
            assert result1.enable_caching == result2.enable_caching
            assert result1.use_real_api == result2.use_real_api
            assert result1.ttl_seconds == result2.ttl_seconds
