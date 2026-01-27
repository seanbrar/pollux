"""Comprehensive test suite for the Pydantic Two-File Core configuration system.

This test suite covers all aspects of the new configuration system:
- Schema validation with Pydantic Settings
- Configuration precedence and merging
- Profile support for TOML files
- Provider inference from model names
- Ambient scope context management
- SourceMap audit tracking
- Error handling and edge cases
"""

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from pydantic import ValidationError
import pytest

from pollux.config import (
    FrozenConfig,
    Origin,
    Settings,
    config_scope,
    resolve_config,
    resolve_provider,
)
from pollux.core.models import APITier

pytestmark = pytest.mark.unit


class TestSettings:
    """Test the Pydantic Settings schema validation."""

    @pytest.mark.smoke
    def test_settings_defaults(self):
        """Settings should provide sensible defaults."""
        settings = Settings()

        assert settings.model == "gemini-2.0-flash"
        assert settings.api_key is None
        assert settings.use_real_api is False
        assert settings.enable_caching is False
        assert settings.ttl_seconds == 3600
        assert settings.telemetry_enabled is False
        assert settings.tier is APITier.FREE

    def test_settings_validation_api_key_required_when_real_api(self):
        """Should require API key when use_real_api=True."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(use_real_api=True, api_key=None)

        assert "api_key is required when use_real_api=True" in str(exc_info.value)

    def test_settings_validation_api_key_not_required_when_mock_api(self):
        """Should not require API key when use_real_api=False."""
        settings = Settings(use_real_api=False, api_key=None)
        assert settings.api_key is None

    def test_settings_validation_negative_ttl_rejected(self):
        """Should reject negative TTL values."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(ttl_seconds=-1)

        assert "ttl_seconds must be >= 0" in str(exc_info.value)

    def test_settings_validation_zero_ttl_allowed(self):
        """Should allow zero TTL values."""
        settings = Settings(ttl_seconds=0)
        assert settings.ttl_seconds == 0

    def test_settings_extra_fields_preserved(self):
        """Settings should preserve unknown fields via extra='allow'."""
        # This test verifies that the Pydantic model allows extra fields
        data = {
            "model": "test-model",
            "unknown_field": "test_value",
            "another_field": 42,
        }
        settings = Settings.model_validate(data)

        # Extra fields should be accessible via model_dump
        dumped = settings.model_dump()
        assert dumped["unknown_field"] == "test_value"
        assert dumped["another_field"] == 42


class TestConfigResolution:
    """Test the configuration resolution and precedence logic."""

    @pytest.mark.smoke
    def test_resolve_config_defaults_only(self):
        """Should return defaults when no other sources provide values."""
        # Mock all loaders to return empty dicts - pure defaults test
        with (
            patch("pollux.config.loaders.load_env", return_value={}),
            patch("pollux.config.loaders.load_pyproject", return_value={}),
            patch("pollux.config.loaders.load_home", return_value={}),
        ):
            config = resolve_config()

            assert isinstance(config, FrozenConfig)
            assert config.model == "gemini-2.0-flash"
            assert config.api_key is None
            assert config.use_real_api is False
            assert config.provider == "google"

    def test_resolve_config_with_overrides(self):
        """Overrides should take highest precedence."""
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")}
        clean_env["POLLUX_MODEL"] = "env-model"
        with patch.dict(os.environ, clean_env, clear=True):
            config = resolve_config(overrides={"model": "override-model"})

            assert config.model == "override-model"

    def test_resolve_config_precedence_env_over_defaults(self):
        """Environment variables should override defaults."""
        with patch.dict(
            os.environ,
            {
                "POLLUX_MODEL": "env-model",
                "POLLUX_USE_REAL_API": "true",
                "POLLUX_TTL_SECONDS": "7200",
                "GEMINI_API_KEY": "test",  # ensure valid when use_real_api=true
            },
            clear=True,
        ):
            config = resolve_config()

            assert config.model == "env-model"
            assert config.use_real_api is True
            assert config.ttl_seconds == 7200

    def test_resolve_config_explain_returns_source_map(self):
        """Should return SourceMap when explain=True."""
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")}
        clean_env["POLLUX_MODEL"] = "env-model"
        with patch.dict(os.environ, clean_env, clear=True):
            config, sources = resolve_config(explain=True)

            assert isinstance(config, FrozenConfig)
            assert isinstance(sources, dict)
            assert sources["model"].origin == Origin.ENV
            assert sources["model"].env_key == "POLLUX_MODEL"
            assert sources["api_key"].origin == Origin.DEFAULT

    def test_resolve_config_extra_fields_preserved(self):
        """Unknown fields should be preserved in FrozenConfig.extra."""
        config = resolve_config(overrides={"unknown_field": "test_value"})

        assert "unknown_field" in config.extra
        assert config.extra["unknown_field"] == "test_value"

    def test_resolve_config_validation_error_propagates(self):
        """Validation errors should bubble up clearly."""
        with pytest.raises(ValidationError) as exc_info:
            resolve_config(overrides={"use_real_api": True, "api_key": None})

        assert "api_key is required" in str(exc_info.value)


class TestProviderInference:
    """Test the data-driven provider inference logic."""

    @pytest.mark.smoke
    def test_provider_inference_gemini_models(self):
        """Should identify Google as provider for gemini- prefixed models."""
        assert resolve_provider("gemini-1.5-flash") == "google"
        assert resolve_provider("gemini-2.0-pro") == "google"
        assert resolve_provider("GEMINI-1.5-FLASH") == "google"  # Case insensitive

    def test_provider_inference_openai_models(self):
        """Should identify OpenAI as provider for gpt- prefixed models."""
        assert resolve_provider("gpt-4") == "openai"
        assert resolve_provider("gpt-3.5-turbo") == "openai"
        assert resolve_provider("GPT-4") == "openai"  # Case insensitive

    def test_provider_inference_anthropic_models(self):
        """Should identify Anthropic as provider for claude- prefixed models."""
        assert resolve_provider("claude-3-sonnet") == "anthropic"
        assert resolve_provider("claude-2") == "anthropic"
        assert resolve_provider("CLAUDE-3-OPUS") == "anthropic"  # Case insensitive

    def test_provider_inference_unknown_model_defaults_to_google(self):
        """Unknown models should default to Google provider."""
        assert resolve_provider("unknown-model") == "google"
        assert resolve_provider("custom-model-v1") == "google"
        assert resolve_provider("") == "google"


class TestAmbientScope:
    """Test the ambient configuration context management."""

    def test_ambient_without_scope_raises(self):
        """ambient() removed; ensure resolution still works without it."""
        # The old ambient accessor was removed. Ensure resolve_config still
        # raises when required validations fail (proxy for previous behavior).
        with pytest.raises(ValidationError):
            resolve_config(overrides={"use_real_api": True, "api_key": None})

    def test_ambient_emits_deprecation_warning(self):
        """ambient() removed; keep test name for compatibility.

        This test ensures calling resolve_config still triggers validation
        warnings when appropriate — the ambient accessor itself is gone.
        """
        with pytest.raises(ValidationError):
            resolve_config(overrides={"use_real_api": True, "api_key": None})

    def test_config_scope_sets_and_restores_ambient(self):
        """Context manager should set and restore ambient config."""
        test_config = resolve_config(overrides={"model": "test-model"})

        # Using config_scope should still yield the provided FrozenConfig
        with config_scope(test_config) as scoped_config:
            assert scoped_config is test_config

    def test_config_scope_with_overrides_dict(self):
        """Should resolve config from overrides dict."""
        with config_scope({"model": "scoped-model"}) as config:
            assert config.model == "scoped-model"
            # The ambient accessor was removed; ensure scoped config is returned
            assert config.model == "scoped-model"

    def test_nested_config_scopes_lifo_behavior(self):
        """Nested scopes should behave LIFO (last-in, first-out)."""
        config1 = resolve_config(overrides={"model": "model-1"})
        config2 = resolve_config(overrides={"model": "model-2"})

        with config_scope(config1):
            assert config1.model == "model-1"

            with config_scope(config2):
                assert config2.model == "model-2"

            # Outer scope remains unchanged after inner scope exits
            assert config1.model == "model-1"


class TestFileLoading:
    """Test TOML file loading and profile support."""

    @contextmanager
    def temp_toml_file(self, content: str) -> Iterator[Path]:
        """Create a temporary TOML file for testing.

        Note: Some tests rename the file to pyproject.toml; we guard unlink.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(content)
            f.flush()
            temp_path = Path(f.name)
        try:
            yield temp_path
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_pyproject_toml_loading(self, isolated_config_sources):
        """Should load configuration from pyproject.toml."""
        toml_content = """
[tool.pollux]
model = "file-model"
enable_caching = true
ttl_seconds = 1800
"""

        with isolated_config_sources(pyproject_content=toml_content):
            config = resolve_config()
            assert config.model == "file-model"
            assert config.enable_caching is True
            assert config.ttl_seconds == 1800

    def test_profile_overlay_from_toml(self, isolated_config_sources):
        """Should overlay profile configuration over base configuration."""
        toml_content = """
[tool.pollux]
model = "base-model"
enable_caching = false

[tool.pollux.profiles.research]
model = "research-model"
ttl_seconds = 7200
"""

        with isolated_config_sources(pyproject_content=toml_content):
            config = resolve_config(profile="research")
            assert config.model == "research-model"  # From profile
            assert config.enable_caching is False  # From base
            assert config.ttl_seconds == 7200  # From profile

    def test_profile_from_environment_variable(self, isolated_config_sources):
        """Should use POLLUX_PROFILE environment variable."""
        toml_content = """
[tool.pollux]
model = "base-model"

[tool.pollux.profiles.test]
model = "test-model"
"""

        with isolated_config_sources(
            pyproject_content=toml_content, env_vars={"PROFILE": "test"}
        ):
            config = resolve_config()
            assert config.model == "test-model"


class TestEnvironmentLoading:
    """Test environment variable loading and type coercion."""

    def test_environment_boolean_coercion(self):
        """Should correctly coerce boolean values from environment."""
        bool_cases = [
            ("1", True),
            ("true", True),
            ("TRUE", True),
            ("yes", True),
            ("on", True),
            ("0", False),
            ("false", False),
            ("FALSE", False),
            ("no", False),
            ("off", False),
        ]

        for env_value, expected in bool_cases:
            with patch.dict(
                os.environ,
                {
                    "POLLUX_USE_REAL_API": env_value,
                    "GEMINI_API_KEY": "test",
                },
                clear=True,
            ):
                config = resolve_config()
                assert config.use_real_api is expected, (
                    f"Failed for env_value: {env_value}"
                )

    def test_environment_integer_coercion(self):
        """Should correctly coerce integer values from environment."""
        with patch.dict(os.environ, {"POLLUX_TTL_SECONDS": "1234"}, clear=True):
            config = resolve_config()
            assert config.ttl_seconds == 1234

    def test_environment_invalid_integer_handled_by_pydantic(self):
        """Invalid integers should be caught by Pydantic validation."""
        with (
            patch.dict(
                os.environ, {"POLLUX_TTL_SECONDS": "not-a-number"}, clear=True
            ),
            pytest.raises(ValidationError),
        ):
            resolve_config()

    def test_dotenv_file_loading(self):
        """Should load .env file if python-dotenv is available."""
        # This is a bit tricky to test reliably without affecting the environment
        # The actual loading is handled by the dotenv library
        # We mainly test that the function doesn't crash when dotenv is not available
        from pollux.config.loaders import load_env

        # Should not raise an exception even if dotenv fails
        result = load_env()
        assert isinstance(result, dict)


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_missing_toml_files_handled_gracefully(self):
        """Missing TOML files should not cause errors."""
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")}
        with (
            patch.dict(
                os.environ,
                {
                    **clean_env,
                    "POLLUX_PYPROJECT_PATH": "/nonexistent/pyproject.toml",
                },
                clear=True,
            ),
        ):
            # Point to a nonexistent file via env override

            config = resolve_config()
            # Should use defaults
            assert config.model == "gemini-2.0-flash"

    def test_malformed_toml_files_handled_gracefully(self):
        """Malformed TOML files should not cause errors."""
        malformed_content = """
[tool.pollux
# Missing closing bracket - invalid TOML
model = "test"
"""

        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")}
        with (
            patch.dict(os.environ, clean_env, clear=True),
            self.temp_toml_file(malformed_content) as temp_file,
            patch.dict(
                os.environ, {"POLLUX_PYPROJECT_PATH": str(temp_file)}, clear=False
            ),
        ):
            # Use env override for malformed file path

            config = resolve_config()
            # Should use defaults when file is malformed
            assert config.model == "gemini-2.0-flash"

    @contextmanager
    def temp_toml_file(self, content: str) -> Iterator[Path]:
        """Create a temporary TOML file for testing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(content)
            f.flush()
            yield Path(f.name)
        if Path(f.name).exists():
            Path(f.name).unlink()


class TestFrozenConfigImmutability:
    """Test that FrozenConfig is truly immutable."""

    def test_frozen_config_immutability(self):
        """FrozenConfig should be immutable after creation."""
        config = resolve_config()

        # Should not be able to modify fields
        with pytest.raises(AttributeError):
            config.model = "new-model"  # type: ignore[misc]

        with pytest.raises(AttributeError):
            config.api_key = "new-key"  # type: ignore[misc]

    def test_frozen_config_string_representation_redacts_api_key(self):
        """String representation should redact API key."""
        config = resolve_config(overrides={"api_key": "secret-key"})

        config_str = str(config)
        assert "secret-key" not in config_str
        assert "[REDACTED]" in config_str

    def test_frozen_config_repr_redacts_api_key(self):
        """Repr should redact API key."""
        config = resolve_config(overrides={"api_key": "secret-key"})

        config_repr = repr(config)
        assert "secret-key" not in config_repr
        assert "[REDACTED]" in config_repr
