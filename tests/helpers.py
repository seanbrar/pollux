"""Test helpers (small, reusable doubles).

Keep this file tiny and purpose-built: it exists to prevent test suites from
growing lots of one-off provider subclasses as coverage expands.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from pollux.errors import APIError, ConfigurationError
from pollux.providers.base import (
    ProviderCapabilities,
    ProviderDeferredHandle,
    ProviderDeferredItem,
    ProviderDeferredSnapshot,
)
from pollux.providers.models import ProviderFileAsset, ProviderRequest, ProviderResponse
from tests.conftest import FakeProvider


@dataclass
class CaptureProvider(FakeProvider):
    """FakeProvider that records generate() kwargs for assertions."""

    generate_calls: int = 0
    generate_kwargs: list[dict[str, Any]] = field(default_factory=list)

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.generate_calls += 1
        self.generate_kwargs.append({"request": request})
        parts = request.parts
        prompt = parts[-1] if parts and isinstance(parts[-1], str) else ""
        return ProviderResponse(text=f"ok:{prompt}", usage={"total_tokens": 1})


@dataclass
class ScriptedProvider(FakeProvider):
    """FakeProvider that returns a scripted sequence of results/exceptions.

    Useful for result/status tests without defining bespoke providers.
    """

    script: list[dict[str, Any] | ProviderResponse | BaseException] = field(
        default_factory=list
    )
    generate_calls: int = 0

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        _ = request
        self.generate_calls += 1
        if not self.script:
            return ProviderResponse(text="ok", usage={"total_tokens": 1})
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, ProviderResponse):
            return item
        return ProviderResponse(**item)


@dataclass
class GateProvider(FakeProvider):
    """FakeProvider with an explicit barrier for upload/cache race tests."""

    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    fail_once: bool = True
    kind: str = "upload"  # "upload" or "cache"
    generate_calls: int = 0

    def __post_init__(self) -> None:
        # Default to a provider that supports everything the caller might assert on.
        object.__setattr__(
            self,
            "_capabilities",
            ProviderCapabilities(
                persistent_cache=True,
                uploads=True,
                structured_outputs=True,
                reasoning=True,
                deferred_delivery=True,
                conversation=True,
            ),
        )

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.generate_calls += 1
        return await super().generate(request)

    async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:
        _ = path, mime_type
        self.upload_calls += 1
        self.started.set()
        await self.release.wait()
        if self.kind == "upload" and self.fail_once:
            self.fail_once = False
            raise APIError(
                "upload failed",
                retryable=False,
                provider="gemini",
                phase="upload",
            )
        return ProviderFileAsset(
            file_id="mock://uploaded/shared.pdf",
            provider="mock",
            mime_type=mime_type,
        )

    async def create_cache(self, **kwargs: Any) -> str:
        _ = kwargs
        self.cache_calls += 1
        self.started.set()
        await self.release.wait()
        if self.kind == "cache" and self.fail_once:
            self.fail_once = False
            raise APIError(
                "cache failed",
                retryable=False,
                provider="gemini",
                phase="cache",
            )
        return "cachedContents/test"


@dataclass
class InMemoryDeferredProvider(FakeProvider):
    """In-memory deferred provider for public API boundary tests."""

    _capabilities: ProviderCapabilities = field(
        default_factory=lambda: ProviderCapabilities(
            persistent_cache=False,
            uploads=True,
            structured_outputs=True,
            reasoning=True,
            deferred_delivery=True,
            conversation=False,
        )
    )
    inspect_status: str = "completed"
    provider_status: str | None = None
    item_overrides: dict[str, ProviderDeferredItem] = field(default_factory=dict)
    submitted_requests: dict[str, list[ProviderRequest]] = field(default_factory=dict)
    submitted_ids: dict[str, list[str]] = field(default_factory=dict)
    cancelled_jobs: list[str] = field(default_factory=list)
    submitted_at: float = 100.0
    completed_at: float | None = 125.0

    async def submit_deferred(
        self,
        requests: list[ProviderRequest],
        *,
        request_ids: list[str],
    ) -> ProviderDeferredHandle:
        job_id = f"job-{len(self.submitted_requests)}"
        self.submitted_requests[job_id] = list(requests)
        self.submitted_ids[job_id] = list(request_ids)
        return ProviderDeferredHandle(
            job_id=job_id,
            submitted_at=self.submitted_at,
            provider_state={"request_ids": list(request_ids)},
        )

    async def inspect_deferred(
        self, handle: ProviderDeferredHandle
    ) -> ProviderDeferredSnapshot:
        job_id = handle.job_id
        request_ids = self.submitted_ids[job_id]
        items = self._collected_items(job_id)
        if self.inspect_status in {"queued", "running", "cancelling"}:
            succeeded = 0
            failed = 0
            pending = len(request_ids)
        else:
            succeeded = sum(1 for item in items if item.status == "succeeded")
            failed = len(items) - succeeded
            pending = 0
        return ProviderDeferredSnapshot(
            status=self.inspect_status,
            provider_status=self.provider_status or self.inspect_status,
            request_count=len(request_ids),
            succeeded=succeeded,
            failed=failed,
            pending=pending,
            submitted_at=self.submitted_at,
            completed_at=self.completed_at if pending == 0 else None,
        )

    async def collect_deferred(
        self, handle: ProviderDeferredHandle
    ) -> list[ProviderDeferredItem]:
        return self._collected_items(handle.job_id)

    async def cancel_deferred(self, handle: ProviderDeferredHandle) -> None:
        self.cancelled_jobs.append(handle.job_id)

    def _collected_items(self, job_id: str) -> list[ProviderDeferredItem]:
        requests = self.submitted_requests[job_id]
        request_ids = self.submitted_ids[job_id]
        items: list[ProviderDeferredItem] = []
        for request_id, request in zip(request_ids, requests, strict=True):
            override = self.item_overrides.get(request_id)
            if override is not None:
                items.append(override)
                continue
            prompt = (
                request.parts[-1]
                if request.parts and isinstance(request.parts[-1], str)
                else ""
            )
            items.append(
                ProviderDeferredItem(
                    request_id=request_id,
                    status="succeeded",
                    response={
                        "text": f"ok:{prompt}",
                        "usage": {"total_tokens": 1},
                    },
                    provider_status="succeeded",
                    finish_reason="stop",
                )
            )
        return items


@dataclass
class RejectingValidatingProvider(FakeProvider):
    """Provider double that fails validation before uploads begin."""

    validation_calls: list[ProviderRequest] = field(default_factory=list)

    async def validate_request(self, request: ProviderRequest) -> None:
        self.validation_calls.append(request)
        raise ConfigurationError(
            "validation failed",
            hint="Validation should run before uploads.",
        )


@dataclass
class RejectingValidatingDeferredProvider(InMemoryDeferredProvider):
    """Deferred provider double that fails validation before submission side effects."""

    validation_calls: list[ProviderRequest] = field(default_factory=list)

    async def validate_request(self, request: ProviderRequest) -> None:
        self.validation_calls.append(request)
        raise ConfigurationError(
            "validation failed",
            hint="Validation should run before deferred uploads.",
        )
