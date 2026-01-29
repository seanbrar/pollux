"""Security contract tests for the configuration system.

Layer 1/2: Contract Compliance + Security Invariants
Prove that secrets are handled securely and never leak into logs/audits.
"""

import os
from unittest.mock import patch

import pytest

from pollux.config import resolve_config


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
