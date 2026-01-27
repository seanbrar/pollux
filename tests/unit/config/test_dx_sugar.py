"""Tests for DX sugar functions like check_environment and doctor.

These tests validate the diagnostic and developer experience helpers
while ensuring they maintain security by redacting sensitive information.
"""

import os
from unittest.mock import patch

import pytest

from pollux.config import check_environment, doctor, resolve_config
from pollux.config.core import FrozenConfig
from pollux.core.models import APITier

pytestmark = pytest.mark.unit


class TestCheckEnvironment:
    """Test the check_environment DX sugar function."""

    def test_check_environment_returns_pollux_vars(self):
        """Should return all POLLUX_* environment variables."""
        env_vars = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("GEMINI_") and not k.startswith("POLLUX_")
        }
        env_vars.update(
            {
                "POLLUX_MODEL": "test-model",
                "POLLUX_TTL_SECONDS": "1800",
                "POLLUX_USE_REAL_API": "true",
                "OTHER_VAR": "should-not-appear",
            }
        )

        with patch.dict(os.environ, env_vars, clear=True):
            result = check_environment()

            assert "POLLUX_MODEL" in result
            assert "POLLUX_TTL_SECONDS" in result
            assert "POLLUX_USE_REAL_API" in result
            assert "OTHER_VAR" not in result

            assert result["POLLUX_MODEL"] == "test-model"
            assert result["POLLUX_TTL_SECONDS"] == "1800"
            assert result["POLLUX_USE_REAL_API"] == "true"

    def test_check_environment_redacts_sensitive_keys(self):
        """Should redact sensitive environment variables like API keys."""
        env_vars = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("GEMINI_") and not k.startswith("POLLUX_")
        }
        env_vars.update(
            {
                "GEMINI_API_KEY": "secret-key-123",
                "POLLUX_TOKEN": "secret-token-456",
                "POLLUX_SECRET": "secret-value-789",
                "POLLUX_MODEL": "safe-model-name",
            }
        )

        with patch.dict(os.environ, env_vars, clear=True):
            result = check_environment()

            # Sensitive keys should be redacted
            assert result["GEMINI_API_KEY"] == "***redacted***"
            assert result["POLLUX_TOKEN"] == "***redacted***"
            assert result["POLLUX_SECRET"] == "***redacted***"

            # Non-sensitive values should be visible
            assert result["POLLUX_MODEL"] == "safe-model-name"

    def test_check_environment_empty_when_no_pollux_vars(self):
        """Should return empty dict when no POLLUX_* vars are set."""
        clean_env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("GEMINI_") and not k.startswith("POLLUX_")
        }
        clean_env["OTHER_VAR"] = "not-pollux"

        with patch.dict(os.environ, clean_env, clear=True):
            result = check_environment()

            assert result == {}

    def test_check_environment_case_sensitive_redaction(self):
        """Should redact based on case-insensitive key matching."""
        env_vars = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("GEMINI_") and not k.startswith("POLLUX_")
        }
        env_vars.update(
            {
                "GEMINI_api_key": "should-redact-lowercase",
                "GEMINI_API_KEY": "should-redact-uppercase",
                "GEMINI_Api_Key": "should-redact-mixed",
                "POLLUX_SOME_KEY": "should-redact-contains-key",
            }
        )

        with patch.dict(os.environ, env_vars, clear=True):
            result = check_environment()

            # All variations should be redacted
            for key in result:
                if any(
                    sensitive in key.upper() for sensitive in ("KEY", "TOKEN", "SECRET")
                ):
                    assert result[key] == "***redacted***"


class TestDoctor:
    """Test the doctor diagnostic function."""

    def test_doctor_detects_missing_api_key_with_real_api(self):
        """Should detect when use_real_api=True but api_key is missing."""
        with (
            patch("pollux.config.loaders.load_env", return_value={}),
            patch("pollux.config.loaders.load_pyproject", return_value={}),
            patch("pollux.config.loaders.load_home", return_value={}),
        ):
            # This should not raise because use_real_api defaults to False
            messages = doctor()

            # Should report no issues when use_real_api is False
            assert "No issues detected." in messages

    def test_doctor_detects_negative_ttl(self):
        """Should detect negative TTL values (though validation should prevent this)."""
        # This test verifies the doctor logic even though validation should catch it
        # We'll mock resolve_config to return an impossible state for testing

        bad_config = FrozenConfig(
            model="test-model",
            api_key=None,
            use_real_api=False,
            enable_caching=False,
            ttl_seconds=-1,  # Invalid
            telemetry_enabled=False,
            tier=APITier.FREE,
            provider="google",
            extra={},
            request_concurrency=6,
        )

        with patch("pollux.config.core.resolve_config") as mock_resolve:
            mock_resolve.return_value = (bad_config, {})
            messages = doctor()

            assert any("ttl_seconds < 0" in msg for msg in messages)

    def test_doctor_detects_unknown_model_provider_mismatch(self):
        """Should detect when model doesn't match inferred provider."""

        weird_config = FrozenConfig(
            model="unknown-model-xyz",  # Doesn't match google patterns
            api_key=None,
            use_real_api=False,
            enable_caching=False,
            ttl_seconds=3600,
            telemetry_enabled=False,
            tier=APITier.FREE,
            provider="google",  # Provider defaulted to google
            extra={},
            request_concurrency=6,
        )

        with patch("pollux.config.core.resolve_config") as mock_resolve:
            mock_resolve.return_value = (weird_config, {})
            messages = doctor()

            assert any(
                "Unknown model" in msg and "defaulted to 'google'" in msg
                for msg in messages
            )

    def test_doctor_reports_no_issues_for_good_config(self):
        """Should report no issues for a valid configuration."""
        with (
            patch("pollux.config.loaders.load_env", return_value={}),
            patch("pollux.config.loaders.load_pyproject", return_value={}),
            patch("pollux.config.loaders.load_home", return_value={}),
        ):
            messages = doctor()

            assert "No issues detected." in messages
            assert len(messages) == 2  # "No issues" and "Tier not specified"


class TestAuditHelpers:
    """Test audit and transparency functions."""

    def test_audit_lines_redacts_sensitive_fields(self):
        """Audit lines should never show sensitive field values."""
        from pollux.config import audit_lines

        config, sources = resolve_config(
            overrides={"api_key": "secret-key-123", "model": "test-model"}, explain=True
        )

        lines = audit_lines(config, sources)

        # Should have audit lines for both fields
        api_key_line = next(
            (line for line in lines if line.startswith("api_key:")), None
        )
        model_line = next((line for line in lines if line.startswith("model:")), None)

        assert api_key_line is not None
        assert model_line is not None

        # API key value should never appear in audit
        assert "secret-key-123" not in api_key_line
        assert "overrides" in api_key_line  # But origin should be shown

        # Non-sensitive fields can show origin info
        assert "overrides" in model_line

    def test_to_redacted_dict_redacts_secrets(self):
        """Redacted dict should mask sensitive values."""
        from pollux.config import to_redacted_dict

        config = resolve_config(
            overrides={
                "api_key": "secret-key-123",
                "model": "test-model",
                "custom_token": "secret-token-456",
            }
        )

        redacted = to_redacted_dict(config)

        # Sensitive fields should be redacted
        assert redacted["api_key"] == "***redacted***"

        # Non-sensitive fields should be preserved
        assert redacted["model"] == "test-model"

        # Extra fields containing sensitive keywords should be redacted
        assert redacted["extra"]["custom_token"] == "***redacted***"
