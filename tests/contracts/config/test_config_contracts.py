"""Contract compliance tests for the configuration system.

Layer 1: Contract Compliance
Prove each configuration component meets its type/behavior contract.
"""

import os
from unittest.mock import patch

import pytest

from pollux.config import resolve_config
from pollux.config.core import FrozenConfig
from pollux.core.exceptions import ConfigurationError
from pollux.core.models import APITier


class TestConfigurationContractCompliance:
    """Contract compliance tests for configuration system components."""

    @pytest.mark.contract
    def test_resolve_config_returns_frozen_and_source_map(self):
        """Contract: resolve_config() returns FrozenConfig, and explain=True returns (FrozenConfig, SourceMap)."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test_key"}):
            cfg = resolve_config()
            assert isinstance(cfg, FrozenConfig)

            cfg2, src = resolve_config(explain=True)
            assert isinstance(cfg2, FrozenConfig)
            assert isinstance(src, dict)
            assert "api_key" in src

    @pytest.mark.contract
    def test_resolve_config_is_pure_function(self):
        """Contract: resolve_config() is a pure function - same inputs produce same outputs."""
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test_key", "POLLUX_MODEL": "test_model"},
        ):
            # Call multiple times with same inputs
            result1 = resolve_config()
            result2 = resolve_config()

            # Should produce identical results (FrozenConfig equality)
            assert result1 == result2

    @pytest.mark.contract
    def test_resolve_config_returns_typed_result(self):
        """Contract: resolve_config() returns properly typed FrozenConfig and origin map when requested."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test_key"}):
            result = resolve_config()
            assert isinstance(result, FrozenConfig)

            cfg, origin = resolve_config(explain=True)
            assert isinstance(cfg, FrozenConfig)
            assert isinstance(origin, dict)
            assert "api_key" in origin

    @pytest.mark.contract
    def test_frozen_config_direct_access_contract(self):
        """Contract: FrozenConfig must provide direct field access."""
        frozen_config = FrozenConfig(
            api_key="test_key",
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

        # Must provide all required fields
        assert hasattr(frozen_config, "api_key")
        assert hasattr(frozen_config, "model")
        assert hasattr(frozen_config, "tier")
        assert hasattr(frozen_config, "enable_caching")
        assert hasattr(frozen_config, "use_real_api")
        assert hasattr(frozen_config, "ttl_seconds")

        # Field access must work
        assert frozen_config.api_key == "test_key"
        assert frozen_config.model == "gemini-2.0-flash"
        assert frozen_config.tier == APITier.FREE

    @pytest.mark.contract
    def test_overrides_flow_contract(self):
        """Contract: overrides should be applied and returned in FrozenConfig."""
        resolved = resolve_config(
            overrides={
                "api_key": "test_key",
                "model": "gemini-2.0-flash",
                "tier": APITier.FREE,
                "enable_caching": True,
                "use_real_api": False,
                "ttl_seconds": 3600,
                "telemetry_enabled": True,
            }
        )
        assert isinstance(resolved, FrozenConfig)
        assert resolved.api_key == "test_key"

    @pytest.mark.contract
    def test_profile_system_deterministic(self):
        """Contract: Profile system should be deterministic when implemented."""
        # For now, test that profile parameter doesn't break resolution
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test_key"}):
            result1 = resolve_config(profile=None)
            result2 = resolve_config(profile=None)

            # Should return identical results
            assert result1 == result2

    @pytest.mark.contract
    def test_configuration_types_are_serializable(self):
        """Contract: Configuration types must be serializable for telemetry."""
        frozen = FrozenConfig(
            api_key="test_key",
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

        # Should be able to extract fields for serialization
        fields = {
            "model": frozen.model,
            "tier": frozen.tier.value
            if frozen.tier is not None
            else None,  # Enum should have value when present
            "enable_caching": frozen.enable_caching,
            "use_real_api": frozen.use_real_api,
            "ttl_seconds": frozen.ttl_seconds,
            # Note: api_key should NOT be serialized (secret)
        }

        # All fields should be JSON-serializable types
        import json

        json.dumps(fields)  # Should not raise

    @pytest.mark.contract
    def test_no_global_mutable_state(self):
        """Contract: Configuration system must not use global mutable state."""
        # Verify multiple resolve operations don't interfere
        with patch.dict(
            os.environ, {"GEMINI_API_KEY": "key1", "POLLUX_MODEL": "model1"}
        ):
            config1 = resolve_config()

        with patch.dict(
            os.environ, {"GEMINI_API_KEY": "key2", "POLLUX_MODEL": "model2"}
        ):
            config2 = resolve_config()

        # Results should be independent
        assert config1.api_key == "key1"
        assert config1.model == "model1"
        assert config2.api_key == "key2"
        assert config2.model == "model2"

    @pytest.mark.contract
    def test_error_handling_is_explicit(self):
        """Contract: Configuration errors must be explicit, not hidden exceptions."""
        # Test missing required API key when use_real_api=True
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError) as exc_info:
                resolve_config(overrides={"use_real_api": True})

            # Error should be descriptive and explicit
            assert "api_key" in str(exc_info.value).lower()

        # Test invalid tier
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "test", "POLLUX_TIER": "invalid_tier"},
        ):
            # resolve_config wraps ValidationErrors into ConfigurationError
            with pytest.raises(ConfigurationError) as exc_info:
                resolve_config()

            # Should mention tier validation
            assert "tier" in str(exc_info.value).lower()
