"""Security contract tests for the configuration system.

Layer 1/2: Contract Compliance + Security Invariants
Prove that secrets are handled securely and never leak into logs/audits.
"""

import os
from unittest.mock import patch

import pytest

from pollux.config import resolve_config
from pollux.core.exceptions import ConfigurationError


class TestConfigurationSecurityContracts:
    """Security contract tests for configuration system."""

    @pytest.mark.contract
    @pytest.mark.security
    def test_api_key_never_in_string_representation(self):
        """Security: API key must never appear in string representations."""
        secret_key = "sk-very-secret-api-key-12345-abcdef"

        with patch.dict(os.environ, {"GEMINI_API_KEY": secret_key}):
            cfg = resolve_config()

            # Check various string representations
            cfg_str = str(cfg)
            cfg_repr = repr(cfg)

            # Secret should not appear in any string representation
            assert secret_key not in cfg_str
            assert secret_key not in cfg_repr

    @pytest.mark.contract
    @pytest.mark.security
    def test_api_key_redacted_in_audit_repr(self):
        """Security: API key must be redacted in audit representation."""
        secret_key = "sk-very-secret-api-key-12345-abcdef"

        with patch.dict(os.environ, {"GEMINI_API_KEY": secret_key}):
            cfg, origin = resolve_config(explain=True)

            # Redacted representation should not contain secret
            from pollux.config.core import audit_text

            redacted_text = audit_text(cfg, origin)
            assert secret_key not in redacted_text

            # Should contain redaction indicator
            redacted_repr_lower = redacted_text.lower()
            assert any(
                indicator in redacted_repr_lower
                for indicator in ["***", "[redacted]", "hidden", "secret"]
            )

    @pytest.mark.contract
    @pytest.mark.security
    def test_source_map_never_contains_secrets(self):
        """Security: Source map must never contain actual secret values."""
        secret_key = "sk-very-secret-api-key-12345-abcdef"

        with patch.dict(os.environ, {"GEMINI_API_KEY": secret_key}):
            _, origin = resolve_config(explain=True)

            # Convert source map to string for searching
            source_map_str = str(origin)
            source_map_repr = repr(origin)

            # Secret should not appear anywhere in source map
            assert secret_key not in source_map_str
            assert secret_key not in source_map_repr

            # Source map should still track the field
            assert "api_key" in origin

    @pytest.mark.contract
    @pytest.mark.security
    def test_exception_messages_dont_leak_secrets(self):
        """Security: Exception messages must not contain secret values."""
        secret_key = "sk-very-secret-api-key-12345-abcdef"

        # Test validation error with secret in context
        with patch.dict(os.environ, {"GEMINI_API_KEY": secret_key}):
            with pytest.raises(ConfigurationError) as exc_info:
                # Force a validation error
                resolve_config(overrides={"ttl_seconds": -1})
            error_msg = str(exc_info.value)

            # Error message should not contain the secret
            assert secret_key not in error_msg
