"""Pipeline boundary tests for the simplified v1 execution flow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
import pytest

import pollux
import pollux.cache
from pollux.cache import CacheHandle, CacheRegistry, compute_cache_key
from pollux.config import Config
from pollux.deferred import DeferredHandle
from pollux.errors import (
    APIError,
    ConfigurationError,
    DeferredNotReadyError,
    PlanningError,
    SourceError,
)
from pollux.options import Options
from pollux.providers.anthropic import AnthropicProvider
from pollux.providers.base import (
    ProviderCapabilities,
    ProviderDeferredHandle,
    ProviderDeferredItem,
    ProviderDeferredSnapshot,
)
from pollux.providers.gemini import GeminiProvider
from pollux.providers.models import (
    Message,
    ProviderFileAsset,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
)
from pollux.providers.openai import OpenAIProvider
from pollux.request import normalize_request
from pollux.retry import RetryPolicy
from pollux.source import Source
from tests.conftest import (
    ANTHROPIC_MODEL,
    CACHE_MODEL,
    GEMINI_MODEL,
    OPENAI_MODEL,
    FakeProvider,
)
from tests.helpers import CaptureProvider as KwargsCaptureProvider
from tests.helpers import GateProvider, ScriptedProvider

if TYPE_CHECKING:
    from pollux.result import ResultEnvelope

pytestmark = pytest.mark.integration


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


@pytest.mark.asyncio
async def test_run_and_run_many_smoke() -> None:
    """Smoke: public API returns stable envelope shapes."""
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with_source = await pollux.run(
        "Summarize this text",
        source=Source.from_text("hello world"),
        config=cfg,
    )

    assert with_source["status"] == "ok"
    assert with_source["answers"] == ["echo: hello world"]
    assert with_source["metrics"]["n_calls"] == 1

    prompt_only = await pollux.run("What is 2+2?", config=cfg)
    assert prompt_only["status"] == "ok"
    assert len(prompt_only["answers"]) == 1

    many = await pollux.run_many(
        prompts=("Q1?", "Q2?"),
        sources=(Source.from_text("shared context"),),
        config=cfg,
    )

    assert many["status"] == "ok"
    assert len(many["answers"]) == 2
    assert many["metrics"]["n_calls"] == 2

    empty = await pollux.run_many(prompts=[], config=cfg)
    assert empty["status"] == "ok"
    assert empty["answers"] == []
    assert empty["metrics"]["n_calls"] == 0


# =============================================================================
# Public API Boundary: Error Paths
# =============================================================================


def test_empty_string_prompt_raises_clear_error() -> None:
    """An empty string prompt is a caller mistake; must fail fast."""
    config = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match="empty or whitespace") as exc:
        normalize_request("", sources=(), config=config)
    assert exc.value.hint is not None


def test_whitespace_only_prompt_raises_clear_error() -> None:
    """A whitespace-only prompt is a caller mistake; must fail fast."""
    config = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match="empty or whitespace") as exc:
        normalize_request("   \n\t  ", sources=(), config=config)
    assert exc.value.hint is not None


def test_batch_with_one_empty_prompt_identifies_index() -> None:
    """In a multi-prompt batch, the error should identify which prompt is bad."""
    config = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match=r"prompts\[1\]") as exc:
        normalize_request(["good prompt", ""], sources=(), config=config)
    assert exc.value.hint is not None


def test_empty_prompt_list_is_valid_noop() -> None:
    """run_many(prompts=[]) is a valid no-op; must not raise."""
    config = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    req = normalize_request([], sources=(), config=config)
    assert req.prompts == ()


def test_request_rejects_non_source_objects() -> None:
    """Source inputs must be explicit Source objects."""
    config = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(SourceError) as exc:
        normalize_request("hello", sources=["not-a-source"], config=config)  # type: ignore[list-item]

    assert "Expected Source" in str(exc.value)
    assert exc.value.hint is not None


@pytest.mark.asyncio
async def test_generate_error_attributes_provider_and_call_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generate failures should carry provider, phase, and call index."""

    @dataclass
    class _Provider(FakeProvider):
        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            parts = request.parts
            prompt = parts[-1] if parts and isinstance(parts[-1], str) else ""
            if prompt == "Q2":
                raise APIError(
                    "bad request",
                    retryable=False,
                    status_code=400,
                    provider="gemini",
                    phase="generate",
                )
            return ProviderResponse(text="ok", usage={"total_tokens": 1})

    fake = _Provider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config, _p=fake: _p)

    cfg = Config(
        provider="gemini",
        model=GEMINI_MODEL,
        use_mock=True,
        retry=RetryPolicy(max_attempts=1),
    )

    with pytest.raises(APIError) as exc:
        await pollux.run_many(prompts=("Q1", "Q2"), config=cfg)

    err = exc.value
    assert err.provider == "gemini"
    assert err.phase == "generate"
    assert err.call_idx == 1


@pytest.mark.asyncio
async def test_upload_error_attributes_provider_and_call_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Upload failures should carry provider, phase, and call index."""

    @dataclass
    class _Provider(FakeProvider):
        async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:  # noqa: ARG002
            raise APIError(
                "upload failed",
                retryable=False,
                provider="openai",
                phase="upload",
            )

    fake = _Provider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config, _p=fake: _p)

    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello")

    cfg = Config(
        provider="openai",
        model=OPENAI_MODEL,
        use_mock=True,
        retry=RetryPolicy(max_attempts=1),
    )

    with pytest.raises(APIError) as exc:
        await pollux.run(
            "Read this",
            source=Source.from_file(file_path),
            config=cfg,
        )

    err = exc.value
    assert err.provider == "openai"
    assert err.phase == "upload"
    assert err.call_idx == 0


@pytest.mark.asyncio
async def test_upload_configuration_errors_propagate_without_internal_wrap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Provider-side upload validation should stay a ConfigurationError."""

    @dataclass
    class _Provider(FakeProvider):
        async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:  # noqa: ARG002
            raise ConfigurationError(
                f"unsupported mime type: {mime_type}",
                hint="Only PDFs are supported.",
            )

    fake = _Provider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config, _p=fake: _p)

    file_path = tmp_path / "data.csv"
    file_path.write_text("a,b\n1,2\n", encoding="utf-8")

    cfg = Config(
        provider="openrouter",
        model=OPENAI_MODEL,
        use_mock=True,
        retry=RetryPolicy(max_attempts=1),
    )

    with pytest.raises(ConfigurationError, match="unsupported mime type: text/csv"):
        await pollux.run(
            "Read this",
            source=Source.from_file(file_path, mime_type="text/csv"),
            config=cfg,
        )


@pytest.mark.asyncio
async def test_cache_error_attributes_provider_without_call_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache failures from create_cache() should carry provider and phase."""

    @dataclass
    class _Provider(FakeProvider):
        async def create_cache(self, **kwargs: Any) -> str:
            _ = kwargs
            raise APIError(
                "cache failed",
                retryable=False,
                provider="gemini",
                phase="cache",
            )

    fake = _Provider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config, _p=fake: _p)

    cfg = Config(
        provider="gemini",
        model=CACHE_MODEL,
        use_mock=True,
        retry=RetryPolicy(max_attempts=1),
    )

    with pytest.raises(APIError) as exc:
        await pollux.create_cache(
            (Source.from_text("cache me"),),
            config=cfg,
        )

    err = exc.value
    assert err.provider == "gemini"
    assert err.phase == "cache"


# =============================================================================
# Provider Lifecycle (Boundary)
# =============================================================================


@pytest.mark.asyncio
async def test_provider_is_closed_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider cleanup should run and must not mask success/failure."""

    @dataclass
    class _Provider(FakeProvider):
        closed: int = 0
        fail_generate: bool = False
        fail_close: bool = False

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            if self.fail_generate:
                raise APIError("bad request", retryable=False, status_code=400)
            return await super().generate(request)

        async def aclose(self) -> None:
            self.closed += 1
            if self.fail_close:
                raise RuntimeError("close failed")

    scenarios: list[tuple[str, bool, bool]] = [
        ("success + close ok", False, False),
        ("success + close fails", False, True),
        ("generate fails + close fails", True, True),
    ]

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    for name, fail_generate, fail_close in scenarios:
        fake = _Provider(fail_generate=fail_generate, fail_close=fail_close)
        monkeypatch.setattr(pollux, "_get_provider", lambda _config, _fake=fake: _fake)

        if fail_generate:
            with pytest.raises(APIError, match="bad request"):
                await pollux.run("Q", config=cfg)
        else:
            result = await pollux.run("Q", config=cfg)
            assert result["status"] == "ok"

        assert fake.closed == 1, name


@pytest.mark.asyncio
async def test_create_cache_closes_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_cache should close provider resources on success and failure."""

    @dataclass
    class _Provider(FakeProvider):
        closed: int = 0
        fail_cache: bool = False

        async def create_cache(
            self,
            *,
            model: str,
            parts: list[Any],
            system_instruction: str | None = None,
            tools: list[dict[str, Any]] | list[Any] | None = None,
            ttl_seconds: int = 3600,
        ) -> str:
            if self.fail_cache:
                raise APIError("cache failed", provider="gemini", phase="cache")
            return await super().create_cache(
                model=model,
                parts=parts,
                system_instruction=system_instruction,
                tools=tools,
                ttl_seconds=ttl_seconds,
            )

        async def aclose(self) -> None:
            self.closed += 1

    cfg = Config(provider="gemini", model=CACHE_MODEL, use_mock=True)
    for fail_cache in (False, True):
        fake = _Provider(fail_cache=fail_cache)
        monkeypatch.setattr(pollux, "_get_provider", lambda _config, _fake=fake: _fake)
        monkeypatch.setattr(pollux.cache, "_registry", CacheRegistry())

        if fail_cache:
            with pytest.raises(APIError, match="cache failed"):
                await pollux.create_cache((Source.from_text("cache me"),), config=cfg)
        else:
            handle = await pollux.create_cache(
                (Source.from_text("cache me"),), config=cfg
            )
            assert isinstance(handle, CacheHandle)

        assert fake.closed == 1


# =============================================================================
# Retry Behavior (Boundary)
# =============================================================================


@pytest.mark.asyncio
async def test_retry_matrix(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Retry should behave predictably for generate and side effects."""

    retry = RetryPolicy(
        max_attempts=2,
        initial_delay_s=0.0,
        max_delay_s=0.0,
        jitter=False,
    )

    @dataclass
    class _Provider(FakeProvider):
        mode: str = "generate_retry"
        generate_calls: int = 0
        upload_attempts: int = 0

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            self.generate_calls += 1
            if self.mode == "generate_retry" and self.generate_calls == 1:
                raise APIError("rate limited", retryable=True, status_code=429)
            if self.mode == "generate_no_retry":
                raise APIError("bad request", retryable=False, status_code=400)

            # Upload scenarios: verify substitution happened before generate().
            if self.mode.startswith("upload_"):
                parts = request.parts
                assert any(
                    isinstance(p, ProviderFileAsset)
                    and p.file_id == "mock://uploaded/doc.txt"
                    for p in parts
                )
            return ProviderResponse(text="ok", usage={"total_tokens": 1})

        async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:
            _ = path, mime_type
            self.upload_attempts += 1
            if self.mode == "upload_retry" and self.upload_attempts == 1:
                raise APIError(
                    "rate limited",
                    retryable=True,
                    status_code=429,
                    retry_after_s=0.0,
                )
            if self.mode == "upload_no_retry":
                raise APIError("upload timed out", provider="gemini", phase="upload")
            return ProviderFileAsset(
                file_id="mock://uploaded/doc.txt", provider="mock", mime_type=mime_type
            )

    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello")

    scenarios: list[tuple[str, bool, int, int]] = [
        ("generate_retry", True, 2, 0),
        ("generate_no_retry", False, 1, 0),
        ("upload_retry", True, 1, 2),
        ("upload_no_retry", False, 0, 1),
    ]

    for mode, expect_ok, expect_generate_calls, expect_upload_attempts in scenarios:
        fake = _Provider(mode=mode)
        monkeypatch.setattr(pollux, "_get_provider", lambda _config, _fake=fake: _fake)
        cfg = Config(
            provider="gemini",
            model=GEMINI_MODEL,
            use_mock=True,
            retry=retry,
        )

        if mode.startswith("upload_"):
            coro = pollux.run(
                "Read this",
                source=Source.from_file(file_path),
                config=cfg,
            )
        else:
            coro = pollux.run("hello", config=cfg)

        if expect_ok:
            result = await coro
            assert result["answers"] == ["ok"]
        else:
            with pytest.raises(APIError):
                await coro

        assert fake.generate_calls == expect_generate_calls
        assert fake.upload_attempts == expect_upload_attempts


@pytest.mark.asyncio
async def test_source_from_json_is_sent_as_inline_content() -> None:
    """JSON sources should be passed as content, not URI placeholders."""
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    source = Source.from_json({"topic": "science"})
    expected = source.content_loader().decode("utf-8")

    result = await pollux.run("Summarize this.", source=source, config=cfg)

    assert result["answers"] == [f"echo: {expected}"]


# =============================================================================
# Pipeline Internals
# =============================================================================


@pytest.mark.asyncio
async def test_cache_single_flight_deduplicates_file_uploads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Concurrent create_cache() calls should share uploads via single-flight."""
    gate = asyncio.Event()
    entered = asyncio.Event()

    @dataclass
    class _SlowCacheProvider(FakeProvider):
        async def create_cache(self, **kwargs: Any) -> str:  # noqa: ARG002
            self.cache_calls += 1
            entered.set()
            await gate.wait()
            return "cachedContents/test"

    fake = _SlowCacheProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    monkeypatch.setattr(pollux.cache, "_registry", CacheRegistry())

    file_path = tmp_path / "shared.txt"
    file_path.write_text("shared content", encoding="utf-8")

    cfg = Config(
        provider="gemini",
        model=CACHE_MODEL,
        use_mock=True,
        retry=RetryPolicy(max_attempts=1),
    )
    source = Source.from_file(file_path)

    t1 = asyncio.create_task(pollux.create_cache((source,), config=cfg))
    await entered.wait()
    t2 = asyncio.create_task(pollux.create_cache((source,), config=cfg))
    # Small yield to let t2 join the singleflight waiters.
    await asyncio.sleep(0)
    gate.set()

    results = await asyncio.gather(t1, t2, return_exceptions=True)
    assert all(isinstance(r, CacheHandle) for r in results)
    assert fake.upload_calls == 1, "concurrent calls should share uploads"
    assert fake.cache_calls == 1, "concurrent calls should share cache creation"


@pytest.mark.asyncio
async def test_cache_single_flight_propagates_failure_and_clears_inflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If cache creation fails, concurrent callers see the error; future calls recover."""
    fake = GateProvider(kind="cache")
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    monkeypatch.setattr(pollux.cache, "_registry", CacheRegistry())

    cfg = Config(
        provider="gemini",
        model=CACHE_MODEL,
        use_mock=True,
        retry=RetryPolicy(max_attempts=1),
    )
    source = Source.from_text("cache me", identifier="same-id")

    t1 = asyncio.create_task(
        pollux.create_cache((source,), config=cfg),
    )
    await fake.started.wait()
    t2 = asyncio.create_task(
        pollux.create_cache((source,), config=cfg),
    )
    fake.release.set()

    results = await asyncio.gather(t1, t2, return_exceptions=True)
    assert len(results) == 2
    assert all(isinstance(r, APIError) for r in results)
    assert fake.cache_calls == 1

    # After the failure, the registry should not be stuck; it should be able to create a cache.
    handle = await pollux.create_cache((source,), config=cfg)
    assert isinstance(handle, CacheHandle)
    assert fake.cache_calls == 2

    # And after a successful cache, additional calls should not recreate it.
    handle2 = await pollux.create_cache((source,), config=cfg)
    assert isinstance(handle2, CacheHandle)
    assert fake.cache_calls == 2


@pytest.mark.asyncio
async def test_file_placeholders_are_uploaded_before_generate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Execution should substitute file placeholders with uploaded URIs."""
    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello")

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    await pollux.run_many(
        ("Read this",), sources=(Source.from_file(file_path),), config=cfg
    )

    assert fake.upload_calls == 1
    assert fake.last_parts is not None
    assert not any(isinstance(p, dict) and "file_path" in p for p in fake.last_parts)
    assert any(
        isinstance(p, ProviderFileAsset) and isinstance(p.file_id, str)
        for p in fake.last_parts
    )


@pytest.mark.asyncio
async def test_gemini_video_settings_survive_upload_substitution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Gemini video settings should survive the file upload substitution step."""
    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    video_path = tmp_path / "lecture.mp4"
    video_path.write_bytes(b"fake-mp4")
    source = Source.from_file(
        video_path, mime_type="video/mp4"
    ).with_gemini_video_settings(start_offset="10s", end_offset="20s", fps=1.0)

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    await pollux.run_many(("Describe the clip",), sources=(source,), config=cfg)

    assert fake.last_parts is not None
    part = fake.last_parts[0]
    assert isinstance(part, dict)
    assert "uri" in part
    assert part["mime_type"] == "video/mp4"
    assert part["provider_hints"] == {
        "video_metadata": {
            "start_offset": "10s",
            "end_offset": "20s",
            "fps": 1.0,
        }
    }


@pytest.mark.asyncio
async def test_upload_single_flight_propagates_failure_and_can_recover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """If an upload fails, waiters should see the error and a later run can succeed."""
    fake = GateProvider(kind="upload")
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "shared.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    cfg = Config(
        provider="gemini",
        model=GEMINI_MODEL,
        use_mock=True,
        retry=RetryPolicy(max_attempts=1),
    )

    task = asyncio.create_task(
        pollux.run_many(
            prompts=("Q1", "Q2"),
            sources=(Source.from_file(file_path, mime_type="application/pdf"),),
            config=cfg,
        )
    )
    await fake.started.wait()
    fake.release.set()

    with pytest.raises(APIError, match="upload failed"):
        await task

    # Upload should be attempted once due to single-flight coordination.
    assert fake.upload_calls == 1
    assert fake.generate_calls == 0

    # A later call should not be stuck and can succeed.
    result = await pollux.run_many(
        prompts=("Q3", "Q4"),
        sources=(Source.from_file(file_path, mime_type="application/pdf"),),
        config=cfg,
    )
    assert result["status"] == "ok"
    assert result["answers"] == ["ok:Q3", "ok:Q4"]
    assert fake.upload_calls == 2
    assert fake.generate_calls == 2


# =============================================================================
# Upload Cleanup (v1.2)
# =============================================================================


@pytest.mark.asyncio
async def test_openai_uploads_are_cleaned_up_after_pipeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """OpenAI file uploads should be deleted after the pipeline completes."""

    @dataclass
    class TrackingProvider(FakeProvider):
        deleted_file_ids: list[str] = field(default_factory=list)

        async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:
            self.upload_calls += 1
            return ProviderFileAsset(
                file_id=f"openai://file/file-{path.name}",
                provider="openai",
                mime_type=mime_type,
            )

        async def delete_file(self, file_id: str) -> None:
            self.deleted_file_ids.append(file_id)

    fake = TrackingProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    result = await pollux.run(
        "Read this",
        source=Source.from_file(file_path, mime_type="application/pdf"),
        config=cfg,
    )

    assert result["status"] == "ok"
    assert fake.upload_calls == 1
    assert fake.deleted_file_ids == ["openai://file/file-doc.pdf"]


@pytest.mark.asyncio
async def test_text_uploads_are_not_cleaned_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Text uploads (openai://text/...) are inline, not server-side files."""

    @dataclass
    class TrackingProvider(FakeProvider):
        deleted_file_ids: list[str] = field(default_factory=list)

        async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:  # noqa: ARG002
            self.upload_calls += 1
            return ProviderFileAsset(
                file_id="aW5saW5lZA==",
                provider="openai",
                mime_type=mime_type,
                is_inline_fallback=True,
            )

        async def delete_file(self, file_id: str) -> None:
            self.deleted_file_ids.append(file_id)

    fake = TrackingProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello")

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    await pollux.run(
        "Read this",
        source=Source.from_file(file_path),
        config=cfg,
    )

    assert fake.upload_calls == 1
    assert fake.deleted_file_ids == []


@pytest.mark.asyncio
async def test_upload_cleanup_failure_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Failed cleanup should be logged, not raised."""

    @dataclass
    class FailingCleanupProvider(FakeProvider):
        async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:  # noqa: ARG002
            self.upload_calls += 1
            return ProviderFileAsset(
                file_id="openai://file/file-broken",
                provider="openai",
                mime_type=mime_type,
            )

        async def delete_file(self, file_id: str) -> None:
            raise RuntimeError(f"delete failed for {file_id}")

    fake = FailingCleanupProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    result = await pollux.run(
        "Read this",
        source=Source.from_file(file_path, mime_type="application/pdf"),
        config=cfg,
    )

    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_cleanup_skips_providers_without_delete_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Providers without delete_file (Gemini, Mock) should skip cleanup silently."""
    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello")

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    result = await pollux.run(
        "Read this",
        source=Source.from_file(file_path),
        config=cfg,
    )

    assert result["status"] == "ok"
    assert not hasattr(fake, "deleted_file_ids")


@pytest.mark.asyncio
async def test_openai_upload_cleanup_runs_even_when_generate_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Uploads should still be cleaned up when generation fails."""

    @dataclass
    class FailingGenerateProvider(FakeProvider):
        deleted_file_ids: list[str] = field(default_factory=list)

        async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:  # noqa: ARG002
            self.upload_calls += 1
            return ProviderFileAsset(
                file_id="openai://file/file-failed-generate",
                provider="openai",
                mime_type=mime_type,
            )

        async def generate(self, request: ProviderRequest) -> ProviderResponse:  # noqa: ARG002
            raise APIError("boom", retryable=False)

        async def delete_file(self, file_id: str) -> None:
            self.deleted_file_ids.append(file_id)

    fake = FailingGenerateProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(APIError, match="boom"):
        await pollux.run(
            "Read this",
            source=Source.from_file(file_path, mime_type="application/pdf"),
            config=cfg,
        )

    assert fake.upload_calls == 1
    assert fake.deleted_file_ids == ["openai://file/file-failed-generate"]


@pytest.mark.asyncio
async def test_provider_validation_runs_before_uploads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Provider-owned validation should reject realtime requests before uploads."""
    fake = RejectingValidatingProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match="validation failed"):
        await pollux.run(
            "Read this",
            source=Source.from_file(file_path, mime_type="application/pdf"),
            config=cfg,
        )

    assert fake.upload_calls == 0
    assert len(fake.validation_calls) == 1


@pytest.mark.asyncio
async def test_duration_includes_upload_cleanup_latency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """duration_s should reflect awaited upload cleanup work."""
    cleanup_delay_s = 0.1

    @dataclass
    class SlowCleanupProvider(FakeProvider):
        async def upload_file(self, path: Any, mime_type: str) -> ProviderFileAsset:  # noqa: ARG002
            self.upload_calls += 1
            return ProviderFileAsset(
                file_id="openai://file/file-slow-cleanup",
                provider="openai",
                mime_type=mime_type,
            )

        async def delete_file(self, file_id: str) -> None:  # noqa: ARG002
            await asyncio.sleep(cleanup_delay_s)

    fake = SlowCleanupProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    result = await pollux.run(
        "Read this",
        source=Source.from_file(file_path, mime_type="application/pdf"),
        config=cfg,
    )

    assert result["status"] == "ok"
    assert result["metrics"]["duration_s"] >= 0.09


@pytest.mark.asyncio
async def test_cached_context_rejects_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When cache is active via Options(cache=handle), passing sources raises ConfigurationError."""
    import time

    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    cfg = Config(
        provider="gemini",
        model=CACHE_MODEL,
        use_mock=True,
    )

    handle = CacheHandle(
        name="cachedContents/test",
        model=CACHE_MODEL,
        provider="gemini",
        expires_at=time.time() + 3600,
    )

    with pytest.raises(ConfigurationError, match="sources cannot be used"):
        await pollux.run_many(
            prompts=("A", "B"),
            sources=(Source.from_text("shared context"),),
            config=cfg,
            options=Options(cache=handle),
        )

    assert fake.last_parts is None


@pytest.mark.asyncio
async def test_options_cache_requires_persistent_cache_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passing Options(cache=...) should fail on providers without persistent caching."""
    import time

    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=False,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=False,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)
    handle = CacheHandle(
        name="cachedContents/test",
        model=OPENAI_MODEL,
        provider="openai",
        expires_at=time.time() + 3600,
    )

    with pytest.raises(ConfigurationError, match="persistent caching"):
        await pollux.run_many(
            prompts=("Q",),
            config=cfg,
            options=Options(cache=handle),
        )


@pytest.mark.asyncio
async def test_options_cache_rejects_expired_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expired cache handles must be rejected before any network I/O."""
    import time

    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    expired = CacheHandle(
        name="cachedContents/test",
        model=GEMINI_MODEL,
        provider="gemini",
        expires_at=time.time() - 1,
    )

    with pytest.raises(ConfigurationError, match="expired"):
        await pollux.run("Q", config=cfg, options=Options(cache=expired))

    assert fake.last_parts is None


@pytest.mark.asyncio
async def test_options_cache_rejects_provider_and_model_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache handles must match the active provider and model."""
    import time

    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    bad_provider = CacheHandle(
        name="cachedContents/test",
        model=GEMINI_MODEL,
        provider="openai",
        expires_at=time.time() + 3600,
    )
    bad_model = CacheHandle(
        name="cachedContents/test",
        model=OPENAI_MODEL,
        provider="gemini",
        expires_at=time.time() + 3600,
    )

    with pytest.raises(ConfigurationError, match="provider does not match"):
        await pollux.run_many(
            prompts=("Q",),
            sources=(Source.from_text("shared context"),),
            config=cfg,
            options=Options(cache=bad_provider),
        )
    with pytest.raises(ConfigurationError, match="model does not match"):
        await pollux.run_many(
            prompts=("Q",),
            sources=(Source.from_text("shared context"),),
            config=cfg,
            options=Options(cache=bad_model),
        )

    assert fake.last_parts is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("option_kwargs", "match"),
    [
        ({"system_instruction": "Be concise."}, "system_instruction cannot be used"),
        (
            {
                "tools": [
                    {
                        "name": "get_weather",
                        "description": "Get weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                        },
                    }
                ]
            },
            "tools cannot be used",
        ),
        ({"tool_choice": "required"}, "tool_choice cannot be used"),
    ],
    ids=["system_instruction", "tools", "tool_choice"],
)
async def test_options_cache_rejects_incompatible_options(
    monkeypatch: pytest.MonkeyPatch,
    option_kwargs: dict[str, Any],
    match: str,
) -> None:
    """Cache handles cannot coexist with system_instruction, tools, or tool_choice."""
    import time

    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    handle = CacheHandle(
        name="cachedContents/test",
        model=GEMINI_MODEL,
        provider="gemini",
        expires_at=time.time() + 3600,
    )

    with pytest.raises(ConfigurationError, match=match):
        await pollux.run_many(
            prompts=("Q",),
            sources=(Source.from_text("shared context"),),
            config=cfg,
            options=Options(cache=handle, **option_kwargs),
        )

    assert fake.last_parts is None


def test_cache_identity_uses_content_digest_not_identifier_only() -> None:
    """Regression: cache identity keys must not collide across distinct sources."""
    model = GEMINI_MODEL

    # Same identifier, different content should not collide.
    same_id_a = Source.from_text("AAAA", identifier="same")
    same_id_b = Source.from_text("BBBB", identifier="same")

    # Different remote identifiers should not collide.
    yt_a = Source.from_youtube("https://www.youtube.com/watch?v=video-a")
    yt_b = Source.from_youtube("https://www.youtube.com/watch?v=video-b")
    uri_a = Source.from_uri("https://example.com/a.pdf", mime_type="application/pdf")
    uri_b = Source.from_uri("https://example.com/b.pdf", mime_type="application/pdf")

    keys = [
        compute_cache_key(model, (same_id_a,)),
        compute_cache_key(model, (same_id_b,)),
        compute_cache_key(model, (yt_a,)),
        compute_cache_key(model, (yt_b,)),
        compute_cache_key(model, (uri_a,)),
        compute_cache_key(model, (uri_b,)),
    ]
    assert len(set(keys)) == len(keys)


def test_cache_identity_varies_with_gemini_video_settings() -> None:
    """Different Gemini video settings should produce distinct cache keys."""
    base = Source.from_youtube("https://www.youtube.com/watch?v=video-a")
    clip_a = base.with_gemini_video_settings(
        start_offset="10s", end_offset="20s", fps=1.0
    )
    clip_b = base.with_gemini_video_settings(
        start_offset="30s", end_offset="40s", fps=1.0
    )

    key_a = compute_cache_key(GEMINI_MODEL, (clip_a,), provider="gemini")
    key_b = compute_cache_key(GEMINI_MODEL, (clip_b,), provider="gemini")

    assert key_a != key_b


def test_cache_identity_ignores_gemini_video_settings_for_other_providers() -> None:
    """Gemini-only video settings should not fragment non-Gemini cache identities."""
    base = Source.from_youtube("https://www.youtube.com/watch?v=video-a")
    gemini_only = base.with_gemini_video_settings(fps=1.0)
    plain = Source.from_youtube("https://www.youtube.com/watch?v=video-a")

    gemini_key = compute_cache_key(GEMINI_MODEL, (gemini_only,), provider="gemini")
    plain_gemini_key = compute_cache_key(GEMINI_MODEL, (plain,), provider="gemini")
    openai_key = compute_cache_key(OPENAI_MODEL, (gemini_only,), provider="openai")
    plain_openai_key = compute_cache_key(OPENAI_MODEL, (plain,), provider="openai")

    assert gemini_key != plain_gemini_key
    assert openai_key == plain_openai_key


@pytest.mark.parametrize(
    ("kwargs_a", "kwargs_b"),
    [
        (
            {"system_instruction": "Be concise."},
            {"system_instruction": "Be verbose."},
        ),
        ({"provider": "gemini"}, {"provider": "openai"}),
        (
            {"provider": "gemini", "api_key": "key-aaa"},
            {"provider": "gemini", "api_key": "key-bbb"},
        ),
    ],
    ids=["system_instruction", "provider", "api_key"],
)
def test_cache_identity_varies_with_parameter(
    kwargs_a: dict[str, str],
    kwargs_b: dict[str, str],
) -> None:
    """Distinct parameter values should produce distinct cache identities."""
    source = Source.from_text("shared context")
    key_a = compute_cache_key(GEMINI_MODEL, (source,), **kwargs_a)  # type: ignore[arg-type]
    key_b = compute_cache_key(GEMINI_MODEL, (source,), **kwargs_b)  # type: ignore[arg-type]
    assert key_a != key_b


@pytest.mark.asyncio
async def test_create_cache_returns_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_cache() should return a CacheHandle with the expected fields."""
    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    monkeypatch.setattr(pollux.cache, "_registry", CacheRegistry())

    cfg = Config(provider="gemini", model=CACHE_MODEL, use_mock=True)
    handle = await pollux.create_cache(
        (Source.from_text("hello"),),
        config=cfg,
        ttl_seconds=600,
    )

    assert isinstance(handle, CacheHandle)
    assert handle.name == "cachedContents/test"
    assert handle.model == CACHE_MODEL
    assert handle.provider == "gemini"
    assert handle.expires_at > 0
    assert fake.cache_calls == 1


@pytest.mark.asyncio
async def test_create_cache_cache_hit_skips_uploads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Repeated create_cache() calls for the same key should not re-upload files."""
    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    monkeypatch.setattr(pollux.cache, "_registry", CacheRegistry())

    file_path = tmp_path / "cache-me.txt"
    file_path.write_text("hello cache", encoding="utf-8")

    cfg = Config(provider="gemini", model=CACHE_MODEL, use_mock=True)
    first = await pollux.create_cache((Source.from_file(file_path),), config=cfg)
    second = await pollux.create_cache((Source.from_file(file_path),), config=cfg)

    assert first.name == second.name
    assert fake.cache_calls == 1
    assert fake.upload_calls == 1


@pytest.mark.asyncio
async def test_create_cache_deduplicates_file_uploads_within_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """Duplicate file sources in a single create_cache() should upload only once."""
    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    monkeypatch.setattr(pollux.cache, "_registry", CacheRegistry())

    file_path = tmp_path / "dup.txt"
    file_path.write_text("same content", encoding="utf-8")

    cfg = Config(provider="gemini", model=CACHE_MODEL, use_mock=True)
    src = Source.from_file(file_path)
    handle = await pollux.create_cache((src, src), config=cfg)

    assert isinstance(handle, CacheHandle)
    assert fake.upload_calls == 1


@pytest.mark.asyncio
async def test_create_cache_rejects_unserializable_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_cache() should raise ConfigurationError for non-dict tool items."""
    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    monkeypatch.setattr(pollux.cache, "_registry", CacheRegistry())

    cfg = Config(provider="gemini", model=CACHE_MODEL, use_mock=True)

    class CustomTool:
        pass

    with pytest.raises(ConfigurationError, match="must be a dictionary") as exc:
        await pollux.create_cache(
            (Source.from_text("hello"),),
            config=cfg,
            tools=[CustomTool()],
        )

    assert exc.value.hint is not None
    assert fake.upload_calls == 0
    assert fake.cache_calls == 0


@pytest.mark.asyncio
async def test_create_cache_rejects_unsupported_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_cache() should raise ConfigurationError for providers without persistent_cache."""
    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=False,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match="persistent caching"):
        await pollux.create_cache(
            (Source.from_text("hello"),),
            config=cfg,
        )


@pytest.mark.asyncio
async def test_create_cache_validates_ttl() -> None:
    """create_cache() should reject invalid ttl_seconds synchronously (via coroutine)."""
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match="ttl_seconds"):
        await pollux.create_cache(
            (Source.from_text("hello"),), config=cfg, ttl_seconds=0
        )
    with pytest.raises(ConfigurationError, match="ttl_seconds"):
        await pollux.create_cache(
            (Source.from_text("hello"),), config=cfg, ttl_seconds=-1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("option_kwargs", "match"),
    [
        ({"response_schema": {"type": "object"}}, "structured outputs"),
        ({"reasoning_effort": "high"}, "reasoning"),
        ({"reasoning_budget_tokens": 0}, "reasoning"),
    ],
    ids=["structured_outputs", "reasoning_effort", "reasoning_budget_tokens"],
)
async def test_option_requires_provider_capability(
    option_kwargs: dict[str, Any],
    match: str,
) -> None:
    """Strict capability checks reject unsupported options."""
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match=match):
        await pollux.run(
            "Q",
            config=cfg,
            options=Options(**option_kwargs),
        )


def test_options_system_instruction_requires_string() -> None:
    """Invalid system_instruction types should fail fast at option construction."""
    with pytest.raises(ConfigurationError, match="system_instruction must be a string"):
        Options(system_instruction=123)  # type: ignore[arg-type]


def test_options_reasoning_budget_tokens_requires_non_negative_int() -> None:
    """Budget-based reasoning control should validate shape at option creation."""
    with pytest.raises(
        ConfigurationError,
        match="reasoning_budget_tokens must be a non-negative integer",
    ):
        Options(reasoning_budget_tokens=-1)


def test_options_reasoning_budget_tokens_rejects_bool() -> None:
    """Boolean values should not be accepted as integer reasoning budgets."""
    with pytest.raises(
        ConfigurationError,
        match="reasoning_budget_tokens must be a non-negative integer",
    ):
        Options(reasoning_budget_tokens=True)


def test_options_reasoning_controls_are_mutually_exclusive() -> None:
    """Qualitative and quantitative reasoning controls should not mix."""
    with pytest.raises(
        ConfigurationError,
        match="reasoning_effort and reasoning_budget_tokens are mutually exclusive",
    ):
        Options(reasoning_effort="high", reasoning_budget_tokens=0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reasoning_options", "expected_effort", "expected_budget"),
    [
        ({"reasoning_effort": "high"}, "high", None),
        ({"reasoning_budget_tokens": 0}, None, 0),
    ],
    ids=["reasoning_effort", "reasoning_budget_tokens"],
)
async def test_options_are_forwarded_when_provider_supports_features(
    monkeypatch: pytest.MonkeyPatch,
    reasoning_options: dict[str, Any],
    expected_effort: str | None,
    expected_budget: int | None,
) -> None:
    """Options should be normalized and passed through to provider.generate()."""

    class ExampleSchema(BaseModel):
        name: str

    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=True,
            reasoning=True,
            reasoning_budget_tokens=True,
            deferred_delivery=True,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    await pollux.run_many(
        ("Q1?",),
        sources=(Source.from_text("context"),),
        config=cfg,
        options=Options(
            system_instruction="Reply in one sentence.",
            response_schema=ExampleSchema,
            **reasoning_options,
            delivery_mode="realtime",
        ),
    )

    assert fake.last_generate_kwargs is not None
    assert fake.last_generate_kwargs["reasoning_effort"] == expected_effort
    assert fake.last_generate_kwargs["reasoning_budget_tokens"] == expected_budget
    assert fake.last_generate_kwargs["history"] is None
    assert fake.last_generate_kwargs["system_instruction"] == "Reply in one sentence."
    response_schema = fake.last_generate_kwargs["response_schema"]
    assert isinstance(response_schema, dict)
    assert response_schema["type"] == "object"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompts", "expected_implicit_caching"),
    [
        (("Q1?",), True),
        (("Q1?", "Q2?"), False),
    ],
    ids=["single_call_on", "multi_call_off"],
)
async def test_implicit_caching_default_heuristic(
    monkeypatch: pytest.MonkeyPatch,
    prompts: tuple[str, ...],
    expected_implicit_caching: bool,  # noqa: FBT001
) -> None:
    """Single-call defaults implicit caching on; multi-call defaults it off."""
    fake = KwargsCaptureProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=False,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=False,
            implicit_caching=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="anthropic", model=ANTHROPIC_MODEL, use_mock=True)

    await pollux.run_many(prompts, config=cfg)

    assert len(fake.generate_kwargs) == len(prompts)
    assert all(
        call["request"].implicit_caching is expected_implicit_caching
        for call in fake.generate_kwargs
    )


@pytest.mark.asyncio
async def test_implicit_caching_requires_provider_capability_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit implicit_caching=True should fail on providers that lack it."""
    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match="implicit caching") as exc:
        await pollux.run(
            "Q1?",
            config=cfg,
            options=Options(implicit_caching=True),
        )

    assert exc.value.hint is not None


@pytest.mark.asyncio
async def test_delivery_mode_deferred_is_explicitly_not_implemented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy deferred mode should fail fast and point callers at the sibling API."""
    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=True,
            reasoning=True,
            reasoning_budget_tokens=True,
            deferred_delivery=True,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match="legacy compatibility shim"):
        await pollux.run_many(
            ("Q1?",),
            config=cfg,
            options=Options(delivery_mode="deferred"),
        )


def test_delivery_mode_realtime_is_accepted_as_legacy_compatibility_shim() -> None:
    """Explicit realtime mode should remain valid for existing callers."""
    options = Options(delivery_mode="realtime")

    assert options.delivery_mode == "realtime"


def test_delivery_mode_deferred_is_accepted_as_legacy_compatibility_shim() -> None:
    """Deferred remains constructible so Pollux can raise migration guidance."""
    options = Options(delivery_mode="deferred")

    assert options.delivery_mode == "deferred"


def test_delivery_mode_rejects_invalid_values() -> None:
    """Invalid delivery_mode values should fail fast with a clear error."""
    with pytest.raises(ConfigurationError, match="must be 'realtime' or 'deferred'"):
        Options(delivery_mode="bogus")


def test_deferred_handle_round_trip_serialization() -> None:
    """Deferred handles should serialize cleanly for downstream persistence."""
    handle = DeferredHandle(
        job_id="job-1",
        provider="openai",
        model="gpt-5-nano",
        request_count=2,
        submitted_at=123.0,
        schema_hash="abc",
        provider_state={"request_ids": ["pollux-000000", "pollux-000001"]},
    )

    assert DeferredHandle.from_dict(handle.to_dict()) == handle


@pytest.mark.asyncio
async def test_defer_many_requires_at_least_one_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deferred jobs should not allow the realtime no-op prompt shape."""
    fake = InMemoryDeferredProvider()
    monkeypatch.setattr(pollux, "_create_provider", lambda *_a, **_kw: fake)
    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match="requires at least one prompt"):
        await pollux.defer_many([], config=cfg)


@pytest.mark.asyncio
async def test_deferred_provider_validation_runs_before_uploads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Deferred provider validation should reject requests before submission uploads."""
    fake = RejectingValidatingDeferredProvider()
    monkeypatch.setattr(pollux, "_create_provider", lambda *_a, **_kw: fake)

    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match="validation failed"):
        await pollux.defer_many(
            ("Q1?",),
            sources=(Source.from_file(file_path, mime_type="application/pdf"),),
            config=cfg,
        )

    assert fake.upload_calls == 0
    assert fake.submitted_requests == {}
    assert len(fake.validation_calls) == 1


@pytest.mark.asyncio
async def test_defer_rejects_global_mock_provider() -> None:
    """Deferred delivery should not be available through the global mock provider."""
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match="does not support deferred delivery"):
        await pollux.defer_many(
            ("Summarize this text", "List two risks"),
            sources=(Source.from_text("shared context"),),
            config=cfg,
        )


@pytest.mark.asyncio
async def test_defer_rejects_redundant_legacy_delivery_mode() -> None:
    """Deferred entry points should tell legacy callers to drop delivery_mode."""
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match="not needed with defer"):
        await pollux.defer_many(
            ("Summarize this text",),
            config=cfg,
            options=Options(delivery_mode="deferred"),
        )


@pytest.mark.asyncio
async def test_defer_collect_smoke_without_lifecycle_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deferred lifecycle calls should use the handle directly."""
    fake = InMemoryDeferredProvider()
    monkeypatch.setattr(pollux, "_create_provider", lambda *_a, **_kw: fake)
    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)

    job = await pollux.defer_many(
        ("Q1?", "Q2?"),
        sources=(Source.from_text("shared"),),
        config=cfg,
    )

    assert job.provider_state is not None
    assert job.provider_state["request_ids"] == ["pollux-000000", "pollux-000001"]
    restored = DeferredHandle.from_dict(job.to_dict())

    snapshot = await pollux.inspect_deferred(restored)
    result = await pollux.collect_deferred(restored)

    assert snapshot.is_terminal is True
    assert snapshot.status == "completed"
    assert result["answers"] == ["ok:Q1?", "ok:Q2?"]
    assert result["metrics"]["deferred"] is True
    assert result["diagnostics"]["deferred"]["job_id"] == job.job_id
    assert [item["status"] for item in result["diagnostics"]["deferred"]["items"]] == [
        "succeeded",
        "succeeded",
    ]


@pytest.mark.asyncio
async def test_collect_deferred_raises_typed_not_ready_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collect should fail fast with the latest snapshot when work is not ready."""
    fake = InMemoryDeferredProvider(inspect_status="running", completed_at=None)
    monkeypatch.setattr(pollux, "_create_provider", lambda *_a, **_kw: fake)
    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)

    job = await pollux.defer("Q1?", config=cfg)

    with pytest.raises(DeferredNotReadyError) as exc:
        await pollux.collect_deferred(job)

    assert exc.value.snapshot.status == "running"
    assert exc.value.snapshot.pending == 1


@pytest.mark.asyncio
async def test_collect_deferred_validates_schema_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collect-time schema drift should fail clearly."""

    class SubmitSchema(BaseModel):
        title: str

    class OtherSchema(BaseModel):
        name: str

    fake = InMemoryDeferredProvider()
    monkeypatch.setattr(pollux, "_create_provider", lambda *_a, **_kw: fake)
    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)

    job = await pollux.defer(
        "Q1?",
        config=cfg,
        options=Options(response_schema=SubmitSchema),
    )

    with pytest.raises(ConfigurationError, match="does not match"):
        await pollux.collect_deferred(job, response_schema=OtherSchema)


@pytest.mark.asyncio
async def test_collect_deferred_without_schema_returns_plain_structured_dicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omitting response_schema at collect time should return plain dicts."""

    class SubmitSchema(BaseModel):
        title: str

    fake = InMemoryDeferredProvider(
        item_overrides={
            "pollux-000000": ProviderDeferredItem(
                request_id="pollux-000000",
                status="succeeded",
                response={
                    "text": '{"title":"A"}',
                    "structured": {"title": "A"},
                    "usage": {"total_tokens": 1},
                },
                provider_status="succeeded",
                finish_reason="stop",
            )
        }
    )
    monkeypatch.setattr(pollux, "_create_provider", lambda *_a, **_kw: fake)
    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)

    job = await pollux.defer(
        "Q1?",
        config=cfg,
        options=Options(response_schema=SubmitSchema),
    )
    result = await pollux.collect_deferred(job)

    assert result["structured"] == [{"title": "A"}]


@pytest.mark.asyncio
async def test_deferred_partial_failures_preserve_order_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial deferred jobs should preserve order and expose per-item status."""
    fake = InMemoryDeferredProvider(
        inspect_status="partial",
        item_overrides={
            "pollux-000001": ProviderDeferredItem(
                request_id="pollux-000001",
                status="failed",
                error="provider error",
                provider_status="errored",
                finish_reason="error",
            )
        },
    )
    monkeypatch.setattr(pollux, "_create_provider", lambda *_a, **_kw: fake)
    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)

    job = await pollux.defer_many(("Q1?", "Q2?"), config=cfg)
    result = await pollux.collect_deferred(job)

    assert result["status"] == "partial"
    assert result["answers"] == ["ok:Q1?", ""]
    assert result["diagnostics"]["deferred"]["items"] == [
        {
            "request_id": "pollux-000000",
            "status": "succeeded",
            "error": None,
            "provider_status": "succeeded",
            "finish_reason": "stop",
        },
        {
            "request_id": "pollux-000001",
            "status": "failed",
            "error": "provider error",
            "provider_status": "errored",
            "finish_reason": "error",
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "match"),
    [
        (
            Options(cache=CacheHandle("c", "openai", OPENAI_MODEL, 9999999999.0)),
            "cache",
        ),
        (
            Options(history=[{"role": "user", "content": "hi"}]),
            "Conversation continuity",
        ),
        (
            Options(tools=[{"type": "function", "function": {"name": "x"}}]),
            "Tool calling",
        ),
        (Options(implicit_caching=True), "implicit_caching"),
        (Options(implicit_caching=False), "implicit_caching"),
    ],
    ids=[
        "cache",
        "history",
        "tools",
        "implicit_caching_true",
        "implicit_caching_false",
    ],
)
async def test_defer_rejects_out_of_scope_options(
    monkeypatch: pytest.MonkeyPatch,
    options: Options,
    match: str,
) -> None:
    """Deferred APIs should reject options that are explicitly out of scope."""
    fake = InMemoryDeferredProvider()
    monkeypatch.setattr(pollux, "_create_provider", lambda *_a, **_kw: fake)
    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match=match):
        await pollux.defer("Q1?", config=cfg, options=options)


@pytest.mark.asyncio
async def test_openai_deferred_backend_integrates_with_public_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI deferred provider should integrate cleanly through Pollux's public API."""

    class _Files:
        def __init__(self) -> None:
            self.deleted_file_ids: list[str] = []
            self.contents = {
                "file_out": "\n".join(
                    [
                        json.dumps(
                            {
                                "custom_id": "pollux-000001",
                                "response": {
                                    "status_code": 200,
                                    "body": {
                                        "status": "completed",
                                        "output": [
                                            {
                                                "type": "message",
                                                "content": [
                                                    {
                                                        "type": "output_text",
                                                        "text": "Answer 2",
                                                    }
                                                ],
                                            }
                                        ],
                                        "usage": {"total_tokens": 1},
                                    },
                                },
                                "error": None,
                            }
                        )
                    ]
                ),
                "file_err": "\n".join(
                    [
                        json.dumps(
                            {
                                "custom_id": "pollux-000000",
                                "error": {
                                    "code": "server_error",
                                    "message": "request failed",
                                },
                            }
                        )
                    ]
                ),
            }

        async def create(self, **kwargs: Any) -> Any:
            _ = kwargs
            return type("File", (), {"id": "file_batch_input"})()

        async def retrieve_content(self, file_id: str) -> str:
            return self.contents[file_id]

        async def delete(self, file_id: str) -> None:
            self.deleted_file_ids.append(file_id)

        async def close(self) -> None:
            return None

    class _Batches:
        def __init__(self) -> None:
            self.cancelled: str | None = None

        async def create(self, **kwargs: Any) -> Any:
            _ = kwargs
            return type("Batch", (), {"id": "batch_123", "created_at": 100.0})()

        async def retrieve(self, job_id: str) -> Any:
            _ = job_id
            return {
                "status": "completed",
                "request_counts": {"total": 2, "completed": 1, "failed": 1},
                "created_at": 100,
                "completed_at": 125,
                "output_file_id": "file_out",
                "error_file_id": "file_err",
            }

        async def cancel(self, job_id: str) -> Any:
            self.cancelled = job_id
            return {"id": job_id}

    batches = _Batches()
    files = _Files()

    def _make_provider(*_args: Any, **_kwargs: Any) -> OpenAIProvider:
        class _Client:
            def __init__(self) -> None:
                self.files = files
                self.batches = batches

            async def close(self) -> None:
                await _async_noop()

        provider = OpenAIProvider("test-key")
        provider._client = _Client()
        return provider

    async def _async_noop() -> None:
        return None

    monkeypatch.setattr(pollux, "_create_provider", _make_provider)
    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)

    job = await pollux.defer_many(("Q1?", "Q2?"), config=cfg)
    snapshot = await pollux.inspect_deferred(job)
    result = await pollux.collect_deferred(job)
    await pollux.cancel_deferred(job)

    assert snapshot.status == "partial"
    assert result["status"] == "partial"
    assert result["answers"] == ["", "Answer 2"]
    assert result["diagnostics"]["deferred"]["items"] == [
        {
            "request_id": "pollux-000000",
            "status": "failed",
            "error": "request failed",
            "provider_status": "server_error",
            "finish_reason": None,
        },
        {
            "request_id": "pollux-000001",
            "status": "succeeded",
            "error": None,
            "provider_status": "completed",
            "finish_reason": "completed",
        },
    ]
    assert batches.cancelled == "batch_123"
    assert "file_batch_input" in files.deleted_file_ids


@pytest.mark.asyncio
async def test_openai_deferred_partial_cancel_returns_partial_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial cancelled batches should collect without missing-item errors."""

    class _Files:
        def __init__(self) -> None:
            self.contents = {
                "file_out": json.dumps(
                    {
                        "custom_id": "pollux-000000",
                        "response": {
                            "status_code": 200,
                            "body": {
                                "status": "completed",
                                "output": [
                                    {
                                        "type": "message",
                                        "content": [
                                            {
                                                "type": "output_text",
                                                "text": "Answer 1",
                                            }
                                        ],
                                    }
                                ],
                                "usage": {"total_tokens": 1},
                            },
                        },
                        "error": None,
                    }
                )
            }

        async def create(self, **kwargs: Any) -> Any:
            _ = kwargs
            return type("File", (), {"id": "file_batch_input"})()

        async def retrieve_content(self, file_id: str) -> str:
            return self.contents[file_id]

        async def delete(self, file_id: str) -> None:
            _ = file_id

    class _Batches:
        async def create(self, **kwargs: Any) -> Any:
            _ = kwargs
            return type("Batch", (), {"id": "batch_123", "created_at": 100.0})()

        async def retrieve(self, job_id: str) -> Any:
            _ = job_id
            return {
                "status": "cancelled",
                "request_counts": {"total": 2, "completed": 1, "failed": 0},
                "created_at": 100,
                "cancelled_at": 125,
                "output_file_id": "file_out",
            }

        async def cancel(self, job_id: str) -> Any:
            return {"id": job_id}

    def _make_provider(*_args: Any, **_kwargs: Any) -> OpenAIProvider:
        class _Client:
            def __init__(self) -> None:
                self.files = _Files()
                self.batches = _Batches()

            async def close(self) -> None:
                return None

        provider = OpenAIProvider("test-key")
        provider._client = _Client()
        return provider

    monkeypatch.setattr(pollux, "_create_provider", _make_provider)
    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)

    job = await pollux.defer_many(("Q1?", "Q2?"), config=cfg)
    snapshot = await pollux.inspect_deferred(job)
    result = await pollux.collect_deferred(job)

    assert snapshot.status == "partial"
    assert snapshot.request_count == 2
    assert snapshot.succeeded == 1
    assert snapshot.failed == 1
    assert snapshot.pending == 0
    assert result["status"] == "partial"
    assert result["answers"] == ["Answer 1", ""]
    assert result["diagnostics"]["deferred"]["items"] == [
        {
            "request_id": "pollux-000000",
            "status": "succeeded",
            "error": None,
            "provider_status": "completed",
            "finish_reason": "completed",
        },
        {
            "request_id": "pollux-000001",
            "status": "cancelled",
            "error": None,
            "provider_status": "cancelled",
            "finish_reason": None,
        },
    ]


@pytest.mark.asyncio
async def test_openai_deferred_collection_does_not_invent_structured_without_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deferred collection should match realtime extraction when no schema was submitted."""

    class _Files:
        def __init__(self) -> None:
            self.contents = {
                "file_out": json.dumps(
                    {
                        "custom_id": "pollux-000000",
                        "response": {
                            "status_code": 200,
                            "body": {
                                "status": "completed",
                                "output": [
                                    {
                                        "type": "message",
                                        "content": [
                                            {
                                                "type": "output_text",
                                                "text": '{"plain":true}',
                                            }
                                        ],
                                    }
                                ],
                                "usage": {"total_tokens": 1},
                            },
                        },
                        "error": None,
                    }
                )
            }

        async def create(self, **kwargs: Any) -> Any:
            _ = kwargs
            return type("File", (), {"id": "file_batch_input"})()

        async def retrieve_content(self, file_id: str) -> str:
            return self.contents[file_id]

        async def delete(self, file_id: str) -> None:
            _ = file_id

    class _Batches:
        async def create(self, **kwargs: Any) -> Any:
            _ = kwargs
            return type("Batch", (), {"id": "batch_123", "created_at": 100.0})()

        async def retrieve(self, job_id: str) -> Any:
            _ = job_id
            return {
                "status": "completed",
                "request_counts": {"total": 1, "completed": 1, "failed": 0},
                "created_at": 100,
                "completed_at": 125,
                "output_file_id": "file_out",
                "metadata": {"pollux_has_response_schema": "0"},
            }

        async def cancel(self, job_id: str) -> Any:
            return {"id": job_id}

    def _make_provider(*_args: Any, **_kwargs: Any) -> OpenAIProvider:
        class _Client:
            def __init__(self) -> None:
                self.files = _Files()
                self.batches = _Batches()

            async def close(self) -> None:
                return None

        provider = OpenAIProvider("test-key")
        provider._client = _Client()
        return provider

    monkeypatch.setattr(pollux, "_create_provider", _make_provider)
    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)

    job = await pollux.defer('Return {"plain":true}', config=cfg)
    result = await pollux.collect_deferred(job)

    assert result["answers"] == ['{"plain":true}']
    assert "structured" not in result


@pytest.mark.asyncio
async def test_openai_deferred_batch_level_failure_returns_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch-level validation failures should collect as a normal deferred error result."""

    class _Files:
        async def create(self, **kwargs: Any) -> Any:
            _ = kwargs
            return type("File", (), {"id": "file_batch_input"})()

        async def retrieve_content(self, file_id: str) -> str:
            raise AssertionError(f"unexpected retrieve_content({file_id})")

        async def delete(self, file_id: str) -> None:
            _ = file_id

    class _Batches:
        async def create(self, **kwargs: Any) -> Any:
            _ = kwargs
            return type("Batch", (), {"id": "batch_123", "created_at": 100.0})()

        async def retrieve(self, job_id: str) -> Any:
            _ = job_id
            return {
                "status": "failed",
                "metadata": {"pollux_request_count": "2"},
                "created_at": 100,
                "failed_at": 125,
                "errors": {
                    "data": [
                        {
                            "code": "model_not_found",
                            "message": "The provided model is not supported by the Batch API.",
                        }
                    ]
                },
            }

        async def cancel(self, job_id: str) -> Any:
            return {"id": job_id}

    def _make_provider(*_args: Any, **_kwargs: Any) -> OpenAIProvider:
        class _Client:
            def __init__(self) -> None:
                self.files = _Files()
                self.batches = _Batches()

            async def close(self) -> None:
                return None

        provider = OpenAIProvider("test-key")
        provider._client = _Client()
        return provider

    monkeypatch.setattr(pollux, "_create_provider", _make_provider)
    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)

    job = await pollux.defer_many(("Q1?", "Q2?"), config=cfg)
    snapshot = await pollux.inspect_deferred(job)
    result = await pollux.collect_deferred(job)

    assert snapshot.status == "failed"
    assert snapshot.request_count == 2
    assert snapshot.failed == 2
    assert snapshot.pending == 0
    assert result["status"] == "error"
    assert result["answers"] == ["", ""]
    assert result["diagnostics"]["deferred"]["items"] == [
        {
            "request_id": "pollux-000000",
            "status": "failed",
            "error": "The provided model is not supported by the Batch API.",
            "provider_status": "model_not_found",
            "finish_reason": None,
        },
        {
            "request_id": "pollux-000001",
            "status": "failed",
            "error": "The provided model is not supported by the Batch API.",
            "provider_status": "model_not_found",
            "finish_reason": None,
        },
    ]


@pytest.mark.asyncio
async def test_gemini_deferred_backend_integrates_with_public_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini deferred provider should integrate cleanly through Pollux's public API."""

    class _Files:
        def __init__(self) -> None:
            self.deleted_file_ids: list[str] = []

        async def delete(self, *, name: str) -> None:
            self.deleted_file_ids.append(name)

    class _Batches:
        def __init__(self) -> None:
            self.cancelled: str | None = None

        async def create(self, **kwargs: Any) -> Any:
            _ = kwargs
            return type("Batch", (), {"name": "batches/123", "create_time": 100.0})()

        async def get(self, *, name: str) -> Any:
            _ = name
            return type(
                "Batch",
                (),
                {
                    "state": "JOB_STATE_PARTIALLY_SUCCEEDED",
                    "create_time": 100.0,
                    "end_time": 125.0,
                    "error": None,
                    "dest": type(
                        "Dest",
                        (),
                        {
                            "inlined_responses": [
                                {
                                    "metadata": {"pollux_request_id": "pollux-000001"},
                                    "response": {
                                        "candidates": [
                                            {
                                                "finish_reason": "STOP",
                                                "content": {
                                                    "parts": [{"text": "Answer 2"}]
                                                },
                                            }
                                        ],
                                        "usage_metadata": {"total_token_count": 1},
                                    },
                                },
                                {
                                    "metadata": {"pollux_request_id": "pollux-000000"},
                                    "error": {
                                        "code": 400,
                                        "message": "request failed",
                                    },
                                },
                            ]
                        },
                    )(),
                },
            )()

        async def cancel(self, *, name: str) -> None:
            self.cancelled = name

    batches = _Batches()
    files = _Files()

    def _make_provider(*_args: Any, **_kwargs: Any) -> GeminiProvider:
        provider = GeminiProvider("test-key")
        provider._client = type(
            "Client",
            (),
            {"aio": type("Aio", (), {"files": files, "batches": batches})()},
        )()
        return provider

    monkeypatch.setattr(pollux, "_create_provider", _make_provider)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    job = await pollux.defer_many(("Q1?", "Q2?"), config=cfg)
    snapshot = await pollux.inspect_deferred(job)
    result = await pollux.collect_deferred(job)
    await pollux.cancel_deferred(job)

    assert snapshot.status == "partial"
    assert result["status"] == "partial"
    assert result["answers"] == ["", "Answer 2"]
    assert result["diagnostics"]["deferred"]["items"] == [
        {
            "request_id": "pollux-000000",
            "status": "failed",
            "error": "request failed",
            "provider_status": "400",
            "finish_reason": None,
        },
        {
            "request_id": "pollux-000001",
            "status": "succeeded",
            "error": None,
            "provider_status": "succeeded",
            "finish_reason": "stop",
        },
    ]
    assert batches.cancelled == "batches/123"


@pytest.mark.asyncio
async def test_anthropic_deferred_backend_integrates_with_public_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anthropic deferred provider should integrate cleanly through Pollux's public API."""

    class _Files:
        def __init__(self) -> None:
            self.deleted_file_ids: list[str] = []

        async def delete(self, file_id: str, **kwargs: Any) -> None:
            _ = kwargs
            self.deleted_file_ids.append(file_id)

    class _AsyncResults:
        def __init__(self, rows: list[Any]) -> None:
            self._rows = rows
            self._index = 0

        def __aiter__(self) -> _AsyncResults:
            self._index = 0
            return self

        async def __anext__(self) -> Any:
            if self._index >= len(self._rows):
                raise StopAsyncIteration
            row = self._rows[self._index]
            self._index += 1
            return row

    class _Batches:
        def __init__(self) -> None:
            self.cancelled: str | None = None

        async def create(self, **kwargs: Any) -> Any:
            _ = kwargs
            return type("Batch", (), {"id": "msgbatch_123", "created_at": 100.0})()

        async def retrieve(self, message_batch_id: str) -> Any:
            _ = message_batch_id
            return type(
                "Batch",
                (),
                {
                    "id": "msgbatch_123",
                    "processing_status": "ended",
                    "created_at": 100.0,
                    "ended_at": 125.0,
                    "expires_at": 200.0,
                    "results_url": "https://example.test/results.jsonl",
                    "request_counts": type(
                        "Counts",
                        (),
                        {
                            "processing": 0,
                            "succeeded": 1,
                            "errored": 0,
                            "canceled": 1,
                            "expired": 0,
                        },
                    )(),
                },
            )()

        def results(self, message_batch_id: str) -> _AsyncResults:
            _ = message_batch_id
            return _AsyncResults(
                [
                    type(
                        "Row",
                        (),
                        {
                            "custom_id": "pollux-000001",
                            "result": type(
                                "Succeeded",
                                (),
                                {
                                    "type": "succeeded",
                                    "message": type(
                                        "Message",
                                        (),
                                        {
                                            "id": "msg_123",
                                            "content": [
                                                type(
                                                    "Block",
                                                    (),
                                                    {
                                                        "type": "text",
                                                        "text": "Answer 2",
                                                    },
                                                )()
                                            ],
                                            "usage": type(
                                                "Usage",
                                                (),
                                                {"input_tokens": 1, "output_tokens": 2},
                                            )(),
                                            "stop_reason": "end_turn",
                                        },
                                    )(),
                                },
                            )(),
                        },
                    )(),
                    type(
                        "Row",
                        (),
                        {
                            "custom_id": "pollux-000000",
                            "result": type("Canceled", (), {"type": "canceled"})(),
                        },
                    )(),
                ]
            )

        async def cancel(self, message_batch_id: str) -> Any:
            self.cancelled = message_batch_id
            return await self.retrieve(message_batch_id)

    batches = _Batches()
    files = _Files()

    def _make_provider(*_args: Any, **_kwargs: Any) -> AnthropicProvider:
        class _Client:
            def __init__(self) -> None:
                self.messages = type("Messages", (), {"batches": batches})()
                self.beta = type("Beta", (), {"files": files})()

            async def close(self) -> None:
                return None

        provider = AnthropicProvider("test-key")
        provider._client = _Client()
        return provider

    monkeypatch.setattr(pollux, "_create_provider", _make_provider)
    cfg = Config(provider="anthropic", model=ANTHROPIC_MODEL, use_mock=True)

    job = await pollux.defer_many(("Q1?", "Q2?"), config=cfg)
    snapshot = await pollux.inspect_deferred(job)
    result = await pollux.collect_deferred(job)
    await pollux.cancel_deferred(job)

    assert snapshot.status == "partial"
    assert result["status"] == "partial"
    assert result["answers"] == ["", "Answer 2"]
    assert result["diagnostics"]["deferred"]["items"] == [
        {
            "request_id": "pollux-000000",
            "status": "cancelled",
            "error": None,
            "provider_status": "canceled",
            "finish_reason": None,
        },
        {
            "request_id": "pollux-000001",
            "status": "succeeded",
            "error": None,
            "provider_status": "succeeded",
            "finish_reason": "stop",
        },
    ]
    assert batches.cancelled == "msgbatch_123"


@pytest.mark.asyncio
async def test_structured_output_returns_pydantic_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structured outputs should validate into model instances when requested."""

    class Paper(BaseModel):
        title: str
        findings: list[str]

    @dataclass
    class _StructuredProvider(FakeProvider):
        _capabilities: ProviderCapabilities = field(
            default_factory=lambda: ProviderCapabilities(
                persistent_cache=True,
                uploads=True,
                structured_outputs=True,
                reasoning=False,
                deferred_delivery=False,
                conversation=False,
            )
        )

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            assert isinstance(request.response_schema, dict)
            return ProviderResponse(
                text='{"title":"A","findings":["x","y"]}',
                structured={"title": "A", "findings": ["x", "y"]},
                usage={"total_tokens": 1},
            )

    fake = _StructuredProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run(
        "Extract",
        config=cfg,
        options=Options(response_schema=Paper),
    )

    assert result["answers"] == ['{"title":"A","findings":["x","y"]}']
    assert "structured" in result
    structured = result["structured"]
    assert isinstance(structured, list)
    assert len(structured) == 1
    assert isinstance(structured[0], Paper)
    assert structured[0].title == "A"


# =============================================================================
# Conversation & Tool-Call Transparency (v1.1-v1.2)
#
# MTMT complexity marker: this cluster is dense (~12 tests) because
# conversation has multiple interacting facets — history forwarding,
# continue_from, tool-call preservation, and state emission.  Each test
# covers a distinct boundary, but if this section keeps growing it may
# signal that the conversation surface should be split out into its own
# boundary file or simplified at the design level.
# =============================================================================


@pytest.mark.asyncio
async def test_conversation_options_are_forwarded_when_provider_supports_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conversation options should pass through when provider supports the feature."""
    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=True,
            reasoning=True,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    await pollux.run_many(
        ("Q1?",),
        config=cfg,
        options=Options(history=[{"role": "user", "content": "hello"}]),
    )
    assert fake.last_generate_kwargs is not None
    assert fake.last_generate_kwargs["history"] == [
        Message(role="user", content="hello")
    ]


@pytest.mark.asyncio
async def test_conversation_requires_single_prompt_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conversation continuity is single-turn per API call in v1.1."""
    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=True,
            reasoning=False,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match="exactly one prompt"):
        await pollux.run_many(
            ("Q1?", "Q2?"),
            config=cfg,
            options=Options(history=[{"role": "user", "content": "hello"}]),
        )


@pytest.mark.asyncio
async def test_continue_from_requires_conversation_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """continue_from must include _conversation_state; valid state is forwarded."""
    fake = KwargsCaptureProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=True,
            reasoning=False,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match="missing _conversation_state"):
        await pollux.run_many(
            ("Q1?",),
            config=cfg,
            options=Options(continue_from={"status": "ok", "answers": ["x"]}),
        )

    previous: ResultEnvelope = {
        "status": "ok",
        "answers": ["x"],
        "_conversation_state": {
            "history": [{"role": "user", "content": "hello"}],
            "response_id": "resp_123",
        },
    }
    await pollux.run_many(
        ("Next?",),
        config=cfg,
        options=Options(continue_from=previous),
    )

    assert len(fake.generate_kwargs) == 1
    assert fake.generate_kwargs[0]["request"].history == [
        Message(role="user", content="hello")
    ]
    assert fake.generate_kwargs[0]["request"].previous_response_id == "resp_123"


@pytest.mark.asyncio
async def test_conversation_result_includes_conversation_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conversation runs should emit continuation state in the result envelope."""

    @dataclass
    class _ConversationProvider(FakeProvider):
        _capabilities: ProviderCapabilities = field(
            default_factory=lambda: ProviderCapabilities(
                persistent_cache=True,
                uploads=True,
                structured_outputs=False,
                reasoning=False,
                deferred_delivery=False,
                conversation=True,
            )
        )

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            _ = request
            return ProviderResponse(
                text="Assistant reply.",
                usage={"total_tokens": 1},
                response_id="resp_next",
            )

    fake = _ConversationProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run(
        "Next question?",
        config=cfg,
        options=Options(history=[{"role": "user", "content": "hello"}]),
    )

    state = result.get("_conversation_state")
    assert isinstance(state, dict)
    assert state["response_id"] == "resp_next"
    assert state["history"] == [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "Next question?"},
        {"role": "assistant", "content": "Assistant reply."},
    ]


@pytest.mark.asyncio
async def test_conversation_state_preserves_provider_state_from_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider response state should be persisted for continue_from loops."""

    @dataclass
    class _ProviderStateConversationProvider(FakeProvider):
        _capabilities: ProviderCapabilities = field(
            default_factory=lambda: ProviderCapabilities(
                persistent_cache=True,
                uploads=True,
                structured_outputs=False,
                reasoning=True,
                deferred_delivery=False,
                conversation=True,
            )
        )

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            _ = request
            return ProviderResponse(
                text="Assistant reply.",
                usage={"total_tokens": 1},
                provider_state={"anthropic_thinking_blocks": [{"type": "thinking"}]},
            )

    fake = _ProviderStateConversationProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="anthropic", model="claude-haiku-4-5", use_mock=True)

    result = await pollux.run(
        "Next question?",
        config=cfg,
        options=Options(history=[{"role": "user", "content": "hello"}]),
    )

    state = result.get("_conversation_state")
    assert isinstance(state, dict)
    assert state["provider_state"] == {
        "anthropic_thinking_blocks": [{"type": "thinking"}]
    }
    assistant = state["history"][-1]
    assert assistant["provider_state"] == {
        "anthropic_thinking_blocks": [{"type": "thinking"}]
    }


@pytest.mark.asyncio
async def test_planning_error_wraps_source_loader_failure() -> None:
    """Source loader failures should surface as PlanningError with context."""

    def _boom() -> bytes:
        raise RuntimeError("boom")

    bad = Source(
        source_type="text",
        identifier="bad-source",
        mime_type="text/plain",
        size_bytes=0,
        content_loader=_boom,
    )

    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(PlanningError, match="Failed to load content"):
        await pollux.run_many(
            ("Q",),
            sources=(bad,),
            config=cfg,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("script", "expected_status", "expected_answers"),
    [
        (
            [
                {"text": "ok", "usage": {"total_tokens": 1}},
                {"text": "", "usage": {"total_tokens": 1}},
            ],
            "partial",
            ["ok", ""],
        ),
        (
            [
                {"text": "", "usage": {"total_tokens": 1}},
                {"text": "", "usage": {"total_tokens": 1}},
            ],
            "error",
            ["", ""],
        ),
    ],
)
async def test_result_status_classification(
    monkeypatch: pytest.MonkeyPatch,
    script: list[dict[str, Any]],
    expected_status: str,
    expected_answers: list[str],
) -> None:
    """Status classification should be stable across refactors."""
    fake = ScriptedProvider(script=list(script))
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run_many(("A", "B"), config=cfg)

    assert result["status"] == expected_status
    assert result["answers"] == expected_answers


@pytest.mark.asyncio
async def test_finish_reasons_forwarded_to_result_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider finish_reason should appear in metrics.finish_reasons."""
    fake = ScriptedProvider(
        script=[
            ProviderResponse(
                text="The answer.", usage={"total_tokens": 5}, finish_reason="stop"
            ),
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run("What?", config=cfg)

    assert result["metrics"]["finish_reasons"] == ["stop"]


@pytest.mark.asyncio
async def test_finish_reasons_none_when_provider_omits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """finish_reasons should contain None when provider does not report it."""
    fake = ScriptedProvider(
        script=[
            ProviderResponse(text="ok", usage={"total_tokens": 1}),
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run("What?", config=cfg)

    assert result["metrics"]["finish_reasons"] == [None]


@pytest.mark.asyncio
async def test_structured_validation_failure_returns_none_in_structured_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When structured payload fails validation, keep answers but set structured=None."""

    class Paper(BaseModel):
        title: str
        year: int

    fake = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=True,
            reasoning=False,
            deferred_delivery=False,
            conversation=False,
        ),
        script=[
            ProviderResponse(
                text='{"title":"A"}',
                structured={"title": "A"},
                usage={"total_tokens": 1},
            )
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run(
        "Extract",
        config=cfg,
        options=Options(response_schema=Paper),
    )

    assert result["answers"] == ['{"title":"A"}']
    assert result["structured"] == [None]


def test_history_accepts_tool_messages() -> None:
    """Options(history=...) with tool-shaped messages should not raise."""
    history: list[dict[str, Any]] = [
        {"role": "user", "content": "What's the weather?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "name": "get_weather", "arguments": '{"loc": "NYC"}'}
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 72}'},
    ]
    opts = Options(history=history)
    assert opts.history == history


def test_history_still_rejects_items_without_role() -> None:
    """Items missing 'role' must still raise ConfigurationError."""
    with pytest.raises(ConfigurationError, match="role"):
        Options(history=[{"content": "no role here"}])


@pytest.mark.asyncio
async def test_tool_call_response_populates_conversation_state_without_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run() without history/continue_from must still populate _conversation_state
    when the response contains tool calls, so continue_tool can work."""

    @dataclass
    class _ToolCallProvider(FakeProvider):
        _capabilities: ProviderCapabilities = field(
            default_factory=lambda: ProviderCapabilities(
                persistent_cache=True,
                uploads=True,
                structured_outputs=False,
                reasoning=False,
                deferred_delivery=False,
                conversation=True,
            )
        )

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            _ = request
            return ProviderResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="call_1", name="pick_color", arguments='{"color":"red"}'
                    )
                ],
                response_id="resp_abc",
            )

    fake = _ToolCallProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    # No history, no continue_from — just tools
    result = await pollux.run(
        "Pick a color.",
        config=cfg,
        options=Options(tools=[{"name": "pick_color"}]),
    )

    # _conversation_state must be present and usable
    state = result.get("_conversation_state")
    assert isinstance(state, dict), (
        "_conversation_state should be populated for tool-call responses"
    )
    assert "history" in state
    assert state["history"][-1]["role"] == "assistant"
    assert state["history"][-1]["tool_calls"] == [
        {"id": "call_1", "name": "pick_color", "arguments": '{"color":"red"}'}
    ]
    assert state.get("response_id") == "resp_abc"

    # The result should also have the tool_calls in the envelope
    assert result.get("tool_calls") == [
        [{"id": "call_1", "name": "pick_color", "arguments": '{"color":"red"}'}]
    ]


@pytest.mark.asyncio
async def test_tool_calls_preserved_in_conversation_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When provider returns tool_calls, conversation state preserves them."""

    @dataclass
    class _ToolCallProvider(FakeProvider):
        _capabilities: ProviderCapabilities = field(
            default_factory=lambda: ProviderCapabilities(
                persistent_cache=True,
                uploads=True,
                structured_outputs=False,
                reasoning=False,
                deferred_delivery=False,
                conversation=True,
            )
        )

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            _ = request
            return ProviderResponse(
                text="",
                tool_calls=[ToolCall(id="call_1", name="get_weather", arguments="{}")],
            )

    fake = _ToolCallProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run(
        "What's the weather?",
        config=cfg,
        options=Options(history=[{"role": "user", "content": "hello"}]),
    )

    state = result.get("_conversation_state")
    assert isinstance(state, dict)
    last_msg = state["history"][-1]
    assert last_msg["role"] == "assistant"
    assert last_msg["tool_calls"] == [
        {"id": "call_1", "name": "get_weather", "arguments": "{}"}
    ]


@pytest.mark.asyncio
async def test_continue_from_preserves_tool_history_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """continue_from with tool messages in history passes them to provider."""
    fake = KwargsCaptureProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    tool_history: list[dict[str, Any]] = [
        {"role": "user", "content": "What's the weather?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "name": "get_weather", "arguments": "{}"}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 72}'},
    ]
    previous: ResultEnvelope = {
        "status": "ok",
        "answers": [""],
        "_conversation_state": {"history": tool_history},
    }

    await pollux.run(
        "Tell me more",
        config=cfg,
        options=Options(continue_from=previous),
    )

    assert len(fake.generate_kwargs) == 1
    received_history = fake.generate_kwargs[0]["request"].history
    assert len(received_history) == 3
    # Verify tool message was preserved (not filtered out)
    assert received_history[2].role == "tool"
    assert received_history[2].tool_call_id == "call_1"
    # Verify assistant tool_calls preserved
    assert received_history[1].tool_calls is not None


@pytest.mark.asyncio
async def test_continue_from_forwards_provider_state_with_history_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """History item provider_state should be forwarded in request.provider_state."""
    fake = KwargsCaptureProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=False,
            reasoning=True,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="anthropic", model="claude-haiku-4-5", use_mock=True)

    previous: ResultEnvelope = {
        "status": "ok",
        "answers": [""],
        "_conversation_state": {
            "history": [
                {"role": "user", "content": "Question"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "call_1", "name": "lookup", "arguments": "{}"}
                    ],
                    "provider_state": {
                        "anthropic_thinking_blocks": [
                            {
                                "type": "thinking",
                                "thinking": "plan",
                                "signature": "sig1",
                            }
                        ]
                    },
                },
            ]
        },
    }

    await pollux.run(
        None,
        config=cfg,
        options=Options(continue_from=previous),
    )

    req = fake.generate_kwargs[0]["request"]
    assert req.provider_state is not None
    history_state = req.provider_state.get("history")
    assert isinstance(history_state, list)
    assert history_state[0] is None
    assert history_state[1] == {
        "anthropic_thinking_blocks": [
            {"type": "thinking", "thinking": "plan", "signature": "sig1"}
        ]
    }


@pytest.mark.asyncio
async def test_continue_tool_mechanics(monkeypatch: pytest.MonkeyPatch) -> None:
    """continue_tool should neatly append tool results and allow None prompt."""
    fake = KwargsCaptureProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    previous: ResultEnvelope = {
        "status": "ok",
        "answers": [""],
        "_conversation_state": {
            "history": [
                {"role": "user", "content": "What is the weather?"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "call_1", "name": "get_weather", "arguments": "{}"}
                    ],
                },
            ]
        },
    }

    tool_results = [
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 72}'}
    ]

    await pollux.continue_tool(
        continue_from=previous,
        tool_results=tool_results,
        config=cfg,
    )

    assert len(fake.generate_kwargs) == 1
    received_history = fake.generate_kwargs[0]["request"].history
    assert len(received_history) == 3
    assert received_history[2].role == "tool"
    assert received_history[2].content == '{"temp": 72}'

    # The prompt part of the internal run() call should be empty since prompt is None
    assert fake.generate_kwargs[0]["request"].parts == []


# =============================================================================
# Reasoning / Thinking (v1.2)
# =============================================================================


@pytest.mark.asyncio
async def test_reasoning_surfaced_in_result_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider reasoning text should appear in ResultEnvelope.reasoning."""
    fake = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            reasoning=True,
        ),
        script=[
            {
                "text": "The answer is 42.",
                "usage": {"total_tokens": 10},
                "reasoning": "Let me think step by step...",
            },
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run(
        "What is the meaning of life?",
        config=cfg,
        options=Options(reasoning_effort="high"),
    )

    assert result["answers"] == ["The answer is 42."]
    assert result["reasoning"] == ["Let me think step by step..."]


@pytest.mark.asyncio
async def test_reasoning_omitted_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ResultEnvelope should not include reasoning key when provider omits it."""
    fake = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            reasoning=True,
        ),
        script=[
            {"text": "Hello.", "usage": {"total_tokens": 5}},
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run("Hi", config=cfg)

    assert "reasoning" not in result


@pytest.mark.asyncio
async def test_reasoning_mixed_across_multi_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-prompt: reasoning=None for calls without thinking content."""
    fake = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            reasoning=True,
        ),
        script=[
            {
                "text": "Answer 1",
                "usage": {"total_tokens": 5},
                "reasoning": "Thought A",
            },
            {"text": "Answer 2", "usage": {"total_tokens": 5}},
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run_many(("Q1?", "Q2?"), config=cfg)

    assert result["answers"] == ["Answer 1", "Answer 2"]
    assert result["reasoning"] == ["Thought A", None]


@pytest.mark.asyncio
async def test_reasoning_tokens_aggregate_in_result_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pipeline should preserve and sum reasoning_tokens across calls."""
    fake = ScriptedProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            reasoning=True,
        ),
        script=[
            {
                "text": "Answer 1",
                "usage": {"total_tokens": 8, "reasoning_tokens": 3},
            },
            {
                "text": "Answer 2",
                "usage": {"total_tokens": 9, "reasoning_tokens": 5},
            },
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    result = await pollux.run_many(
        ("Q1?", "Q2?"),
        config=cfg,
        options=Options(reasoning_effort="high"),
    )

    assert result["usage"]["reasoning_tokens"] == 8
    assert result["usage"]["total_tokens"] == 17
