"""Mock provider for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import ProviderRequest, ProviderResponse

if TYPE_CHECKING:
    from pathlib import Path


class MockProvider:
    """Mock provider for testing without API calls.

    Supports caching and uploads but returns synthetic responses.
    """

    @property
    def supports_caching(self) -> bool:
        """Whether this provider supports caching."""
        return self.capabilities.caching

    @property
    def supports_uploads(self) -> bool:
        """Whether this provider supports file uploads."""
        return self.capabilities.uploads

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return supported feature flags."""
        return ProviderCapabilities(
            caching=True,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=False,
        )

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        """Return a deterministic mock response.

        Echo the first non-empty string part, falling back to the last string
        part (typically the prompt). This keeps file-based recipes informative
        in mock mode.
        """
        string_parts = [p for p in request.parts if isinstance(p, str) and p.strip()]
        if string_parts:
            text = string_parts[0]
        else:
            text = next((p for p in reversed(request.parts) if isinstance(p, str)), "")
        return ProviderResponse(
            text=f"echo: {text[:100]}",
            usage={"input_tokens": 10, "total_tokens": 20},
        )

    async def upload_file(self, path: Path, mime_type: str) -> str:  # noqa: ARG002
        """Return a mock upload URI."""
        return f"mock://uploaded/{path.name}"

    async def create_cache(
        self,
        *,
        model: str,
        parts: list[Any],  # noqa: ARG002
        system_instruction: str | None = None,  # noqa: ARG002
        ttl_seconds: int = 3600,  # noqa: ARG002
    ) -> str:
        """Return a mock cache name."""
        return f"cachedContents/mock-{model}"
