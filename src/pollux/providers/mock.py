"""Mock provider for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pollux.providers.base import ProviderCapabilities

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

    async def generate(
        self,
        *,
        model: str,  # noqa: ARG002
        parts: list[Any],
        system_instruction: str | None = None,  # noqa: ARG002
        cache_name: str | None = None,  # noqa: ARG002
        response_schema: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,  # noqa: ARG002
        history: list[dict[str, str]] | None = None,  # noqa: ARG002
        delivery_mode: str = "realtime",  # noqa: ARG002
        previous_response_id: str | None = None,  # noqa: ARG002
    ) -> dict[str, Any]:
        """Return a deterministic mock response.

        Echo the first non-empty string part, falling back to the last string
        part (typically the prompt). This keeps file-based recipes informative
        in mock mode.
        """
        # Explicitly discard so ruff doesn't depend on per-version unused-arg rules.
        del response_schema

        string_parts = [p for p in parts if isinstance(p, str) and p.strip()]
        if string_parts:
            text = string_parts[0]
        else:
            text = next((p for p in reversed(parts) if isinstance(p, str)), "")
        return {
            "text": f"echo: {text[:100]}",
            "usage": {"input_tokens": 10, "total_tokens": 20},
            "mock": True,
        }

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
