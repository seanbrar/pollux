"""Provider adapter registry for the pipeline.

This module implements the adapter seam that keeps provider-specific logic
out of the config module while allowing adapters to customize their configuration.
Following the principle: one seam for SDK calls, explicit boundaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pollux.config import FrozenConfig


class ProviderAdapter(Protocol):
    """Protocol for provider adapters that can customize configuration.

    This is the single seam where provider-specific logic enters the system.
    Adapters may optionally provide configuration customization and other
    provider-specific capabilities.
    """

    name: str

    def build_provider_config(self, cfg: FrozenConfig) -> Mapping[str, Any]:
        """Build provider-specific configuration from FrozenConfig.

        This allows adapters to transform the generic FrozenConfig into
        provider-specific shapes while keeping config resolution generic.

        Args:
            cfg: The resolved, immutable configuration.

        Returns:
            Provider-specific configuration mapping.
        """
        ...


class _AdapterRegistry:
    """Internal registry for provider adapters.

    This maintains a simple mapping from provider names to adapters,
    following the principle of explicit seams and single SDK integration point.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        """Register a provider adapter by its name.

        Args:
            adapter: The adapter instance to register.
        """
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> ProviderAdapter | None:
        """Get an adapter by provider name.

        Args:
            name: Provider name (e.g., "google", "openai").

        Returns:
            The registered adapter or None if not found.
        """
        return self._adapters.get(name)

    def list_providers(self) -> list[str]:
        """List all registered provider names.

        Returns:
            Sorted list of provider names.
        """
        return sorted(self._adapters.keys())


# Global registry instance
_registry = _AdapterRegistry()


def register_adapter(adapter: ProviderAdapter) -> None:
    """Register a provider adapter globally.

    This is the main public API for registering adapters. Typically called
    at module import time by adapter implementations.

    Args:
        adapter: The adapter instance to register.

    Example:
        register_adapter(GeminiAdapter())
    """
    _registry.register(adapter)


def get_adapter(name: str) -> ProviderAdapter | None:
    """Get a registered adapter by provider name.

    Args:
        name: Provider name to look up.

    Returns:
        The adapter instance or None if not found.
    """
    return _registry.get(name)


def build_provider_config(provider: str, cfg: FrozenConfig) -> Mapping[str, Any]:
    """Build provider-specific configuration using the adapter seam.

    This is the single point where generic FrozenConfig gets transformed
    into provider-specific shapes. If no adapter is registered, returns
    empty dict (graceful degradation).

    Args:
        provider: Provider name (e.g., "google").
        cfg: The resolved, immutable configuration.

    Returns:
        Provider-specific configuration mapping.
    """
    adapter = get_adapter(provider)
    if adapter is not None:
        return adapter.build_provider_config(cfg)
    return {}


def list_registered_providers() -> list[str]:
    """List all registered provider names.

    Returns:
        Sorted list of provider names that have registered adapters.
    """
    return _registry.list_providers()
