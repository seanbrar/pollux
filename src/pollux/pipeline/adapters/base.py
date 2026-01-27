"""Provider adapter contracts for API execution.

Small, explicit Protocols to keep the API handler decoupled from SDKs.
Also provides base classes for common adapter patterns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping
    import os

    from pollux.config import FrozenConfig


@runtime_checkable
class GenerationAdapter(Protocol):
    """Minimal protocol for provider generation capability."""

    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],
        api_config: dict[str, object],
    ) -> dict[str, Any]:
        """Generate content for the given model/parts using provider SDK."""
        ...


@runtime_checkable
class UploadsCapability(Protocol):
    """Optional protocol for upload support (duck-typed)."""

    async def upload_file_local(
        self, path: str | os.PathLike[str], mime_type: str | None
    ) -> Any:
        """Upload a local file and return a provider-specific reference."""
        ...


@runtime_checkable
class CachingCapability(Protocol):
    """Optional protocol for cache support (duck-typed)."""

    async def create_cache(
        self,
        *,
        model_name: str,
        content_parts: tuple[Any, ...],
        system_instruction: str | None,
        ttl_seconds: int | None,
    ) -> str:
        """Create a provider cache and return its identifier."""
        ...


@runtime_checkable
class ExecutionHintsAware(Protocol):
    """Optional protocol for adapters that accept execution hints."""

    def apply_hints(self, hints: Any) -> None:  # pragma: no cover - optional
        """Apply execution hints such as cache names or routing info.

        Hints are advisory and adapter-specific; callers should not rely on
        them being applied. Adapters may ignore hints without affecting
        correctness.
        """
        ...


class BaseProviderAdapter:
    """Base implementation for provider adapters.

    This provides a default implementation of the ProviderAdapter protocol
    that can be subclassed by specific provider implementations.
    """

    name: str = "base"

    def build_provider_config(self, cfg: FrozenConfig) -> Mapping[str, Any]:
        """Build provider-specific configuration from FrozenConfig.

        Default implementation returns a basic configuration suitable for
        most providers. Subclasses should override to customize.

        Args:
            cfg: The resolved, immutable configuration.

        Returns:
            Basic provider configuration mapping.
        """
        return {
            "model": cfg.model,
            "api_key": cfg.api_key,
            "use_real_api": cfg.use_real_api,
            "enable_caching": cfg.enable_caching,
            "ttl_seconds": cfg.ttl_seconds,
        }
