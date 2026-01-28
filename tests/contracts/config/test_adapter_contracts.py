import pytest

from pollux.config import resolve_config
from pollux.pipeline.adapters.base import BaseProviderAdapter
from pollux.pipeline.adapters.registry import (
    build_provider_config,
    register_adapter,
)


class TestAdapterContracts:
    """Test that adapter seam maintains configuration system invariants."""

    @pytest.mark.contract
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

    @pytest.mark.contract
    def test_adapter_seam_is_explicit_boundary(self):
        """Adapter building should only happen at explicit seam points."""
        config = resolve_config(overrides={"model": "test-model"})

        # Config object should not contain provider-specific logic
        assert not hasattr(config, "build_provider_config")

        # Provider config building should be explicit call
        provider_config = build_provider_config(config.provider, config)
        assert isinstance(provider_config, dict)
