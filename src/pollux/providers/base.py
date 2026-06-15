"""Provider protocols for realtime and deferred execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from pollux.config import Config
    from pollux.interaction.environment import EnvironmentSnapshot
    from pollux.interaction.input import Input
    from pollux.interaction.requirements import OutputRequirements
    from pollux.providers.models import (
        ProviderFileAsset,
        ProviderResponse,
    )

DeferredItemStatus = Literal["succeeded", "failed", "cancelled", "expired"]


@dataclass(frozen=True)
class ProviderCapabilities:
    """Feature flags exposed by providers."""

    persistent_cache: bool
    uploads: bool
    structured_outputs: bool = False
    reasoning: bool = False
    reasoning_budget_tokens: bool = False
    deferred_delivery: bool = False
    conversation: bool = False
    implicit_caching: bool = False
    file_rejection_hint: str | None = None


@dataclass(frozen=True)
class ProviderDeferredHandle:
    """Provider-owned handle returned at deferred submission time."""

    job_id: str
    submitted_at: float | None = None
    provider_state: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProviderDeferredSnapshot:
    """Provider snapshot normalized to Pollux lifecycle semantics."""

    status: str
    provider_status: str
    request_count: int
    succeeded: int
    failed: int
    pending: int
    submitted_at: float | None = None
    completed_at: float | None = None
    expires_at: float | None = None


@dataclass(frozen=True)
class ProviderDeferredItem:
    """One collected deferred item keyed by the submitted request id."""

    request_id: str
    status: DeferredItemStatus
    response: dict[str, Any] | None = None
    error: str | None = None
    provider_status: str | None = None
    finish_reason: str | None = None


@runtime_checkable
class Provider(Protocol):
    """Minimal provider protocol: compile primitives and generate a response.

    ``generate`` receives the canonical v2 primitives and owns the upstream
    request shaping and response parsing. File uploads and persistent caching
    are optional capabilities expressed through the :class:`FileUploadingProvider`
    and :class:`CachingProvider` structural protocols, detected via ``isinstance``.
    """

    async def generate(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> ProviderResponse:
        """Compile one interaction turn and return the provider response facets."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Feature capabilities for strict option validation."""
        ...


@runtime_checkable
class FileUploadingProvider(Protocol):
    """Optional provider hook for uploading local files to provider storage."""

    async def upload_file(self, path: Path, mime_type: str) -> ProviderFileAsset:
        """Upload a file and return its asset representation."""
        ...


@runtime_checkable
class CachingProvider(Protocol):
    """Optional provider hook for creating persistent context caches."""

    async def create_cache(
        self,
        *,
        model: str,
        parts: list[Any],
        system_instruction: str | None = None,
        tools: list[dict[str, Any]] | list[Any] | None = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """Create a cache and return its name."""
        ...


@runtime_checkable
class CloseableProvider(Protocol):
    """Optional provider hook for releasing transport resources."""

    async def aclose(self) -> None:
        """Close client resources (HTTP clients, sessions)."""
        ...


@runtime_checkable
class FileDeletingProvider(Protocol):
    """Optional provider hook for deleting provider-managed uploaded files."""

    async def delete_file(self, file_id: str) -> None:
        """Delete a previously uploaded file by its provider id."""
        ...


@runtime_checkable
class ValidatingProvider(Protocol):
    """Optional provider hook for request validation before side effects."""

    async def validate_request(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> None:
        """Fail fast on unsupported model- or request-specific features."""
        ...


@runtime_checkable
class DeferredProvider(Protocol):
    """Lifecycle operations for provider-backed deferred delivery."""

    async def submit_deferred(
        self,
        snapshot: EnvironmentSnapshot,
        inputs: list[Input],
        requirements: OutputRequirements,
        config: Config,
        *,
        request_ids: list[str],
    ) -> ProviderDeferredHandle:
        """Submit deferred work and return a provider-owned handle."""
        ...

    async def inspect_deferred(
        self, handle: ProviderDeferredHandle
    ) -> ProviderDeferredSnapshot:
        """Inspect deferred job state."""
        ...

    async def collect_deferred(
        self, handle: ProviderDeferredHandle
    ) -> list[ProviderDeferredItem]:
        """Collect terminal deferred results."""
        ...

    async def cancel_deferred(self, handle: ProviderDeferredHandle) -> None:
        """Request provider-side cancellation."""
        ...
