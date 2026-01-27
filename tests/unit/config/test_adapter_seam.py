"""Tests for the provider adapter seam integration.

This test suite validates that the adapter pattern correctly separates
configuration resolution from provider-specific logic while maintaining
the architectural invariants.
"""

from typing import Any

import pytest

from pollux.config import FrozenConfig, resolve_config
from pollux.pipeline.adapters.base import BaseProviderAdapter
from pollux.pipeline.adapters.registry import (
    build_provider_config,
    get_adapter,
    register_adapter,
)


class TestAdapterSeam:
    """Test the provider adapter registration and configuration building."""

    @pytest.mark.unit
    def test_adapter_registration_and_lookup(self):
        """Should register and retrieve adapters by name."""

        class TestAdapter(BaseProviderAdapter):
            name = "test-provider"

            def build_provider_config(self, cfg: FrozenConfig) -> dict[str, Any]:
                return {"test_field": "test_value", "model": cfg.model}

        adapter = TestAdapter()
        register_adapter(adapter)

        # Should be able to retrieve the adapter
        retrieved = get_adapter("test-provider")
        assert retrieved is adapter
        assert retrieved.name == "test-provider"

    @pytest.mark.unit
    def test_build_provider_config_with_registered_adapter(self):
        """Should use registered adapter to build provider config."""

        class CustomAdapter(BaseProviderAdapter):
            name = "custom"

            def build_provider_config(self, cfg: FrozenConfig) -> dict[str, Any]:
                return {
                    "custom_model": cfg.model,
                    "custom_api_key": cfg.api_key,
                    "custom_field": "custom_value",
                }

        register_adapter(CustomAdapter())

        config = resolve_config(
            overrides={"model": "test-model", "api_key": "test-key"}
        )
        provider_config = build_provider_config("custom", config)

        assert provider_config["custom_model"] == "test-model"
        assert provider_config["custom_api_key"] == "test-key"
        assert provider_config["custom_field"] == "custom_value"

    @pytest.mark.unit
    def test_build_provider_config_without_adapter(self):
        """Should gracefully degrade when no adapter is registered."""
        config = resolve_config(overrides={"model": "unknown-model"})
        provider_config = build_provider_config("nonexistent", config)

        # Should return empty dict for unknown providers
        assert provider_config == {}

    @pytest.mark.unit
    def test_gemini_adapter_registered_on_import(self):
        """Gemini adapter should be registered when module is imported."""
        # Import the module to trigger registration
        from pollux.pipeline.adapters import gemini  # noqa: F401

        adapter = get_adapter("google")
        assert adapter is not None
        assert adapter.name == "google"

    @pytest.mark.unit
    def test_gemini_adapter_build_config(self):
        """Gemini adapter should build appropriate configuration."""
        from pollux.pipeline.adapters import gemini  # noqa: F401

        config = resolve_config(
            overrides={
                "model": "gemini-1.5-flash",
                "api_key": "test-key",
                "use_real_api": True,
                "enable_caching": True,
                "ttl_seconds": 1800,
            }
        )

        provider_config = build_provider_config("google", config)

        assert provider_config["model"] == "gemini-1.5-flash"
        assert provider_config["api_key"] == "test-key"
        assert provider_config["use_real_api"] is True
        assert provider_config["enable_caching"] is True
        assert provider_config["ttl_seconds"] == 1800

    @pytest.mark.unit
    def test_adapter_seam_preserves_extras(self):
        """Adapter should have access to extra fields from configuration."""
        from pollux.pipeline.adapters import gemini  # noqa: F401

        config = resolve_config(
            overrides={
                "model": "gemini-1.5-flash",
                "timeout_s": 30,
                "base_url": "https://custom.api.com",
            }
        )

        provider_config = build_provider_config("google", config)

        # Gemini adapter should include extras if present
        assert provider_config.get("timeout_s") == 30
        assert provider_config.get("base_url") == "https://custom.api.com"


class TestConfigInvariantsWithAdapters:
    """Test that adapter seam maintains configuration system invariants."""

    @pytest.mark.unit
    def test_config_resolution_independent_of_adapters(self):
        """Configuration resolution should not depend on adapter registry."""
        # Resolve config before any adapters are registered
        config1 = resolve_config(overrides={"model": "test-model"})

        # Register an adapter
        class DummyAdapter(BaseProviderAdapter):
            name = "dummy"

        register_adapter(DummyAdapter())

        # Config resolution should be identical
        config2 = resolve_config(overrides={"model": "test-model"})

        assert config1.model == config2.model
        assert config1.provider == config2.provider

    @pytest.mark.unit
    def test_adapter_seam_is_explicit_boundary(self):
        """Adapter building should only happen at explicit seam points."""
        config = resolve_config(overrides={"model": "test-model"})

        # Config object should not contain provider-specific logic
        assert not hasattr(config, "build_provider_config")

        # Provider config building should be explicit call
        provider_config = build_provider_config(config.provider, config)
        assert isinstance(provider_config, dict)
