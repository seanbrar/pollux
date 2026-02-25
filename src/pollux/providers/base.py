"""Provider protocol: minimal interface for API providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from pollux.providers.models import ProviderRequest, ProviderResponse


@dataclass(frozen=True)
class ProviderCapabilities:
    """Feature flags exposed by providers."""

    caching: bool
    uploads: bool
    structured_outputs: bool = False
    reasoning: bool = False
    deferred_delivery: bool = False
    conversation: bool = False


@runtime_checkable
class Provider(Protocol):
    """Minimal provider protocol: generate, upload, create_cache."""

    async def generate(
        self,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """Generate content from the model."""
        ...

    async def upload_file(self, path: Path, mime_type: str) -> str:
        """Upload a file and return its URI."""
        ...

    async def create_cache(
        self,
        *,
        model: str,
        parts: list[Any],
        system_instruction: str | None = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """Create a cache and return its name."""
        ...

    @property
    def supports_caching(self) -> bool:
        """Whether this provider supports caching."""
        ...

    @property
    def supports_uploads(self) -> bool:
        """Whether this provider supports file uploads."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Feature capabilities for strict option validation."""
        ...
