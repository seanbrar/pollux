"""Pipeline boundary tests for the simplified v1 execution flow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
import pytest

import pollux
from pollux.cache import CacheRegistry, compute_cache_key
from pollux.config import Config
from pollux.errors import APIError, ConfigurationError, PlanningError, SourceError
from pollux.options import Options
from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import (
    Message,
    ProviderFileAsset,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
)
from pollux.request import normalize_request
from pollux.retry import RetryPolicy
from pollux.source import Source
from tests.conftest import CACHE_MODEL, GEMINI_MODEL, OPENAI_MODEL, FakeProvider
from tests.helpers import CaptureProvider as KwargsCaptureProvider
from tests.helpers import GateProvider, ScriptedProvider

if TYPE_CHECKING:
    from pollux.result import ResultEnvelope

pytestmark = pytest.mark.integration


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
async def test_cache_error_attributes_provider_without_call_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache failures should carry provider and phase but no call index."""

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
        enable_caching=True,
        retry=RetryPolicy(max_attempts=1),
    )

    with pytest.raises(APIError) as exc:
        await pollux.run_many(
            ("Q",),
            sources=(Source.from_text("cache me"),),
            config=cfg,
        )

    err = exc.value
    assert err.provider == "gemini"
    assert err.phase == "cache"
    assert err.call_idx is None


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
async def test_cache_single_flight_propagates_failure_and_clears_inflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If cache creation fails, all waiters should see the error and future calls can recover."""
    fake = GateProvider(kind="cache")
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    monkeypatch.setattr(pollux, "_registry", CacheRegistry())

    cfg = Config(
        provider="gemini",
        model=CACHE_MODEL,
        use_mock=True,
        enable_caching=True,
        retry=RetryPolicy(max_attempts=1),
    )
    source = Source.from_text("cache me", identifier="same-id")

    t1 = asyncio.create_task(
        pollux.run_many(("A",), sources=(source,), config=cfg),
    )
    await fake.started.wait()
    t2 = asyncio.create_task(
        pollux.run_many(("B",), sources=(source,), config=cfg),
    )
    fake.release.set()

    results = await asyncio.gather(t1, t2, return_exceptions=True)
    assert len(results) == 2
    assert all(isinstance(r, APIError) for r in results)
    assert fake.cache_calls == 1

    # After the failure, the registry should not be stuck; it should be able to create a cache.
    result = await pollux.run_many(("C",), sources=(source,), config=cfg)
    assert result["status"] == "ok"
    assert fake.cache_calls == 2

    # And after a successful cache, additional calls should not recreate it.
    result2 = await pollux.run_many(("D",), sources=(source,), config=cfg)
    assert result2["status"] == "ok"
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
async def test_cached_context_is_not_resent_on_each_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When cache is active, call payloads should include only prompt-specific parts."""

    @dataclass
    class PartsCaptureProvider(FakeProvider):
        received_parts: list[list[Any]] = field(default_factory=list)
        cache_names: list[str | None] = field(default_factory=list)

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            self.received_parts.append(request.parts)
            self.cache_names.append(request.cache_name)
            prompt = (
                request.parts[-1]
                if request.parts and isinstance(request.parts[-1], str)
                else ""
            )
            return ProviderResponse(text=f"ok:{prompt}", usage={"total_tokens": 1})

    fake = PartsCaptureProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    monkeypatch.setattr(pollux, "_registry", CacheRegistry())

    cfg = Config(
        provider="gemini",
        model=CACHE_MODEL,
        use_mock=True,
        enable_caching=True,
    )
    await pollux.run_many(
        prompts=("A", "B"),
        sources=(Source.from_text("shared context"),),
        config=cfg,
    )

    assert fake.cache_calls == 1
    assert fake.cache_names == ["cachedContents/test", "cachedContents/test"]
    assert fake.received_parts == [["A"], ["B"]]


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


def test_cache_identity_includes_system_instruction() -> None:
    """Distinct system instructions should produce distinct cache identities."""
    model = GEMINI_MODEL
    source = Source.from_text("shared context")

    concise = compute_cache_key(
        model,
        (source,),
        system_instruction="Be concise.",
    )
    verbose = compute_cache_key(
        model,
        (source,),
        system_instruction="Be verbose.",
    )

    assert concise != verbose


@pytest.mark.asyncio
async def test_options_response_schema_requires_provider_capability() -> None:
    """Strict capability checks reject unsupported structured outputs."""
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match="structured outputs"):
        await pollux.run(
            "Extract fields",
            config=cfg,
            options=Options(response_schema={"type": "object"}),
        )


@pytest.mark.asyncio
async def test_reasoning_effort_requires_provider_capability() -> None:
    """Strict capability checks reject unsupported reasoning controls."""
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)
    with pytest.raises(ConfigurationError, match="reasoning"):
        await pollux.run(
            "Think about this",
            config=cfg,
            options=Options(reasoning_effort="high"),
        )


def test_options_system_instruction_requires_string() -> None:
    """Invalid system_instruction types should fail fast at option construction."""
    with pytest.raises(ConfigurationError, match="system_instruction must be a string"):
        Options(system_instruction=123)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_options_are_forwarded_when_provider_supports_features(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Options should be normalized and passed through to provider.generate()."""

    class ExampleSchema(BaseModel):
        name: str

    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            caching=True,
            uploads=True,
            structured_outputs=True,
            reasoning=True,
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
            reasoning_effort="high",
            delivery_mode="realtime",
        ),
    )

    assert fake.last_generate_kwargs is not None
    assert fake.last_generate_kwargs["reasoning_effort"] == "high"
    assert fake.last_generate_kwargs["history"] is None
    assert fake.last_generate_kwargs["system_instruction"] == "Reply in one sentence."
    response_schema = fake.last_generate_kwargs["response_schema"]
    assert isinstance(response_schema, dict)
    assert response_schema["type"] == "object"


@pytest.mark.asyncio
async def test_delivery_mode_deferred_is_explicitly_not_implemented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deferred delivery should fail clearly until backend support lands."""
    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            caching=True,
            uploads=True,
            structured_outputs=True,
            reasoning=True,
            deferred_delivery=True,
            conversation=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model=GEMINI_MODEL, use_mock=True)

    with pytest.raises(ConfigurationError, match="not implemented yet"):
        await pollux.run_many(
            ("Q1?",),
            config=cfg,
            options=Options(delivery_mode="deferred"),
        )


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
                caching=True,
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
            caching=True,
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
            caching=True,
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
            caching=True,
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
                caching=True,
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
                caching=True,
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
            caching=True,
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
                caching=True,
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
                caching=True,
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
            caching=True,
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
            caching=True,
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
            caching=True,
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
            caching=True,
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
            caching=True,
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
            caching=True,
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
            caching=True,
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
