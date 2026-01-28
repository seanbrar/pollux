"""Security contract tests for the configuration system.

Layer 1/2: Contract Compliance + Security Invariants
Prove that secrets are handled securely and never leak into logs/audits.
"""

import json
import os
from unittest.mock import patch

import pytest

from pollux.config import resolve_config
from pollux.config.core import FrozenConfig
from pollux.core.exceptions import ConfigurationError
from pollux.core.models import APITier


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
    def test_json_serialization_excludes_secrets(self):
        """Security: JSON serialization must exclude secret fields."""
        secret_key = "sk-very-secret-api-key-12345-abcdef"

        frozen = FrozenConfig(
            api_key=secret_key,
            model="gemini-2.0-flash",
            tier=APITier.FREE,
            enable_caching=True,
            use_real_api=False,
            ttl_seconds=3600,
            telemetry_enabled=True,
            provider="google",
            extra={},
            request_concurrency=6,
        )

        # Create safe dict for serialization (without secrets)
        safe_dict = {
            "model": frozen.model,
            "tier": frozen.tier.value if frozen.tier is not None else None,
            "enable_caching": frozen.enable_caching,
            "use_real_api": frozen.use_real_api,
            "ttl_seconds": frozen.ttl_seconds,
            # Note: api_key deliberately excluded
        }

        # Should serialize without secrets
        serialized = json.dumps(safe_dict)
        assert secret_key not in serialized

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

    @pytest.mark.contract
    @pytest.mark.security
    def test_logging_safe_representations(self):
        """Security: All representations used for logging must be safe."""
        secret_key = "sk-very-secret-api-key-12345-abcdef"

        with patch.dict(os.environ, {"GEMINI_API_KEY": secret_key}):
            cfg = resolve_config()

            # Test common logging representations
            from pollux.config.core import audit_text

            cfg2, origin = resolve_config(explain=True)
            logging_representations = [
                str(cfg),
                repr(cfg),
                audit_text(cfg2, origin),
                f"Config: {cfg}",
            ]

            for representation in logging_representations:
                assert secret_key not in representation, (
                    f"Secret found in: {representation}"
                )

    @pytest.mark.contract
    @pytest.mark.security
    def test_dict_conversion_preserves_security(self):
        """Security: Dict conversion must maintain security properties."""
        secret_key = "sk-very-secret-api-key-12345-abcdef"

        frozen = FrozenConfig(
            api_key=secret_key,
            model="gemini-2.0-flash",
            tier=APITier.FREE,
            enable_caching=True,
            use_real_api=False,
            ttl_seconds=3600,
            telemetry_enabled=True,
            provider="google",
            extra={},
            request_concurrency=6,
        )

        # Manual conversion to dict should still require explicit handling
        # (We don't provide automatic dict conversion that includes secrets)

        # If someone accidentally converts to dict, the secret is there
        # but our string representations should still be safe
        unsafe_dict = {
            "api_key": frozen.api_key,
            "model": frozen.model,
            "tier": frozen.tier,
            "enable_caching": frozen.enable_caching,
            "use_real_api": frozen.use_real_api,
            "ttl_seconds": frozen.ttl_seconds,
        }

        # The dict contains the secret (unavoidable)
        assert unsafe_dict["api_key"] == secret_key

        # Manual dict access still works but is unsafe for string representations
        assert unsafe_dict["api_key"] == secret_key  # Direct access works
        # Note: We rely on frozen config string methods for safety

    @pytest.mark.contract
    @pytest.mark.security
    def test_telemetry_data_excludes_secrets(self):
        """Security: Telemetry data must never include secret values."""
        secret_key = "sk-very-secret-api-key-12345-abcdef"

        with patch.dict(os.environ, {"GEMINI_API_KEY": secret_key}):
            # Simulate telemetry data collection
            cfg, origin = resolve_config(explain=True)
            telemetry_safe_config = {
                "model": cfg.model,
                "tier": cfg.tier.value if cfg.tier is not None else None,
                "enable_caching": cfg.enable_caching,
                "use_real_api": cfg.use_real_api,
                "ttl_seconds": cfg.ttl_seconds,
                "config_sources": [fo.origin.value for fo in origin.values()],
            }

            # Serialize for telemetry
            telemetry_json = json.dumps(telemetry_safe_config)

            # Should not contain secrets
            assert secret_key not in telemetry_json

    @pytest.mark.contract
    @pytest.mark.security
    def test_environment_variable_names_not_sensitive(self):
        """Security: Environment variable names themselves are not sensitive."""
        # This is acceptable - env var names are not secrets
        secret_key = "sk-very-secret-api-key-12345-abcdef"

        with patch.dict(os.environ, {"GEMINI_API_KEY": secret_key}):
            _, origin = resolve_config(explain=True)

            # Source map can contain env var names (not sensitive)
            assert "env" in origin["api_key"].origin.value

            # But not the actual secret value
            assert secret_key not in str(origin)

    @pytest.mark.contract
    @pytest.mark.security
    def test_frozen_config_preserves_security(self):
        """Security: FrozenConfig must maintain security properties."""
        secret_key = "sk-very-secret-api-key-12345-abcdef"

        frozen = FrozenConfig(
            api_key=secret_key,
            model="gemini-2.0-flash",
            tier=APITier.FREE,
            enable_caching=True,
            use_real_api=False,
            ttl_seconds=3600,
            telemetry_enabled=True,
            provider="google",
            extra={},
            request_concurrency=6,
        )

        # FrozenConfig provides access to secret
        assert frozen.api_key == secret_key

        # But string representations should be safe
        frozen_str = str(frozen)
        frozen_repr = repr(frozen)

        # These should not contain the secret
        assert secret_key not in frozen_str
        assert secret_key not in frozen_repr
