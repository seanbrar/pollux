"""Test helpers (small, reusable doubles).

Keep this file tiny and purpose-built: it exists to prevent test suites from
growing lots of one-off provider subclasses as coverage expands.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from pollux.config import Config
from pollux.errors import APIError, ConfigurationError
from pollux.interaction.environment import EnvironmentSnapshot
from pollux.interaction.input import Input
from pollux.interaction.requirements import OutputRequirements
from pollux.interaction.tools import ToolDeclaration, ToolResult
from pollux.providers.base import (
    ProviderCapabilities,
    ProviderDeferredHandle,
    ProviderDeferredItem,
    ProviderDeferredSnapshot,
)
from pollux.providers.models import ProviderFileAsset, ProviderResponse
from tests.conftest import FakeProvider

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pollux.config import ProviderName
    from pollux.interaction.continuation import Continuation, Message


def make_interaction(
    *,
    model: str,
    provider: str = "mock",
    content: str | None = None,
    prepared_parts: Sequence[Any] = (),
    instructions: str | None = None,
    tools: Sequence[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    response_schema: Any = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    seed: int | None = None,
    reasoning_effort: str | None = None,
    reasoning_budget_tokens: int | None = None,
    provider_options: dict[str, dict[str, Any]] | None = None,
    history: Sequence[Message] | None = None,
    continuation: Continuation | None = None,
    tool_results: Sequence[ToolResult] = (),
    cache_name: str | None = None,
    implicit_caching: bool = False,
    base_url: str | None = None,
) -> tuple[EnvironmentSnapshot, Input, OutputRequirements, Config]:
    """Build the four v2 primitives a flipped ``provider.generate`` consumes.

    Contract tests call ``provider.generate`` directly (bypassing core), so they
    set ``prepared_parts`` (the uploaded shared source parts) and ``cache_name``
    on the snapshot themselves, exactly as the execution path would.
    """
    snapshot = EnvironmentSnapshot(
        instructions=instructions,
        tools=tuple(ToolDeclaration.from_dict(t) for t in (tools or ())),
        provider=provider,
        prepared_parts=tuple(prepared_parts),
        cache_name=cache_name,
        implicit_caching=implicit_caching,
    )
    inp = Input(
        content=content,
        history=tuple(history) if history is not None else None,
        continuation=continuation,
        tool_results=tool_results,
    )
    requirements = OutputRequirements(
        output_schema=response_schema,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        seed=seed,
        reasoning_effort=reasoning_effort,
        reasoning_budget_tokens=reasoning_budget_tokens,
        tool_choice=tool_choice,
        provider_options=provider_options,
    )
    config = Config(
        provider=cast("ProviderName", provider),
        model=model,
        use_mock=base_url is None,
        base_url=base_url,
    )
    return snapshot, inp, requirements, config


@dataclass
class ScriptedProvider(FakeProvider):
    """FakeProvider that returns a scripted sequence of results/exceptions.

    Useful for result/status tests without defining bespoke providers.
    """

    script: list[dict[str, Any] | ProviderResponse | BaseException] = field(
        default_factory=list
    )
    generate_calls: int = 0

    async def generate(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> ProviderResponse:
        _ = snapshot, input, requirements, config
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

    async def generate(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> ProviderResponse:
        self.generate_calls += 1
        return await super().generate(snapshot, input, requirements, config)

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
    submitted_requests: dict[str, list[Input]] = field(default_factory=dict)
    submitted_ids: dict[str, list[str]] = field(default_factory=dict)
    cancelled_jobs: list[str] = field(default_factory=list)
    submitted_at: float = 100.0
    completed_at: float | None = 125.0

    async def submit_deferred(
        self,
        snapshot: EnvironmentSnapshot,
        inputs: list[Input],
        requirements: OutputRequirements,
        config: Config,
        *,
        request_ids: list[str],
    ) -> ProviderDeferredHandle:
        _ = snapshot, requirements, config
        job_id = f"job-{len(self.submitted_requests)}"
        self.submitted_requests[job_id] = list(inputs)
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
        inputs = self.submitted_requests[job_id]
        request_ids = self.submitted_ids[job_id]
        items: list[ProviderDeferredItem] = []
        for request_id, inp in zip(request_ids, inputs, strict=True):
            override = self.item_overrides.get(request_id)
            if override is not None:
                items.append(override)
                continue
            prompt = inp.content or ""
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

    validation_calls: list[Input] = field(default_factory=list)

    async def validate_request(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> None:
        _ = snapshot, requirements, config
        self.validation_calls.append(input)
        raise ConfigurationError(
            "validation failed",
            hint="Validation should run before uploads.",
        )


@dataclass
class RejectingValidatingDeferredProvider(InMemoryDeferredProvider):
    """Deferred provider double that fails validation before submission side effects."""

    validation_calls: list[Input] = field(default_factory=list)

    async def validate_request(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> None:
        _ = snapshot, requirements, config
        self.validation_calls.append(input)
        raise ConfigurationError(
            "validation failed",
            hint="Validation should run before deferred uploads.",
        )
