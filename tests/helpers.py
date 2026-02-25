"""Test helpers (small, reusable doubles).

Keep this file tiny and purpose-built: it exists to prevent test suites from
growing lots of one-off provider subclasses as coverage expands.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from pollux.errors import APIError
from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import ProviderRequest, ProviderResponse
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
                caching=True,
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

    async def upload_file(self, path: Any, mime_type: str) -> str:
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
        return "mock://uploaded/shared.pdf"

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
