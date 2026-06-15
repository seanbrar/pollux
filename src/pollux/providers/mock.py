"""Mock provider for testing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pollux.providers import _compile
from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import ProviderFileAsset, ProviderResponse

if TYPE_CHECKING:
    from pathlib import Path

    from pollux.config import Config
    from pollux.interaction.environment import EnvironmentSnapshot
    from pollux.interaction.input import Input
    from pollux.interaction.requirements import OutputRequirements


def _echo_text(parts: list[Any]) -> str:
    """Pick the first non-empty string part, falling back to the last string part."""
    string_parts = [p for p in parts if isinstance(p, str) and p.strip()]
    if string_parts:
        return string_parts[0]
    return next((p for p in reversed(parts) if isinstance(p, str)), "")


class MockProvider:
    """Mock provider for testing without API calls.

    Supports caching and uploads but returns synthetic responses.
    """

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return supported feature flags."""
        return ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=False,
            implicit_caching=False,
        )

    async def generate(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,  # noqa: ARG002
        config: Config,  # noqa: ARG002
    ) -> ProviderResponse:
        """Return a deterministic mock response.

        Echo the first non-empty string part, falling back to the last string
        part (typically the prompt). This keeps file-based recipes informative
        in mock mode.
        """
        parts = _compile.request_parts(snapshot, input)
        return ProviderResponse(
            text=f"echo: {_echo_text(parts)[:100]}",
            usage={"input_tokens": 10, "total_tokens": 20},
        )

    async def upload_file(self, path: Path, mime_type: str) -> ProviderFileAsset:
        """Return a mock upload asset."""
        return ProviderFileAsset(
            file_id=f"mock://uploaded/{path.name}",
            provider="mock",
            mime_type=mime_type,
        )

    async def create_cache(
        self,
        *,
        model: str,
        parts: list[Any],  # noqa: ARG002
        system_instruction: str | None = None,  # noqa: ARG002
        tools: list[dict[str, Any]] | list[Any] | None = None,  # noqa: ARG002
        ttl_seconds: int = 3600,  # noqa: ARG002
    ) -> str:
        """Return a mock cache name."""
        return f"cachedContents/mock-{model}"
