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
from pollux.request import normalize_request
from pollux.retry import RetryPolicy
from pollux.source import Source
from tests.conftest import FakeProvider
from tests.helpers import CaptureProvider as KwargsCaptureProvider
from tests.helpers import GateProvider, ScriptedProvider

if TYPE_CHECKING:
    from pollux.result import ResultEnvelope

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_run_returns_result_envelope() -> None:
    """Single prompt run should return one answer with metrics."""
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    result = await pollux.run(
        "Summarize this text",
        source=Source.from_text("hello world"),
        config=cfg,
    )

    assert result["status"] == "ok"
    assert result["answers"] == ["echo: hello world"]
    assert result["metrics"]["n_calls"] == 1


@pytest.mark.asyncio
async def test_run_many_returns_one_answer_per_prompt() -> None:
    """Vectorized prompts should produce one answer per prompt."""
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    result = await pollux.run_many(
        prompts=("Q1?", "Q2?"),
        sources=(Source.from_text("shared context"),),
        config=cfg,
    )

    assert result["status"] == "ok"
    assert len(result["answers"]) == 2
    assert result["metrics"]["n_calls"] == 2


# =============================================================================
# Public API Boundary: Error Paths
# =============================================================================


def test_request_rejects_non_source_objects() -> None:
    """Source inputs must be explicit Source objects."""
    config = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)
    with pytest.raises(SourceError) as exc:
        normalize_request("hello", sources=["not-a-source"], config=config)  # type: ignore[list-item]

    assert "Expected Source" in str(exc.value)
    assert exc.value.hint is not None


@pytest.mark.asyncio
async def test_run_many_with_empty_prompts_returns_empty_result() -> None:
    """Empty prompt list should return empty answers (idempotent behavior)."""
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    result = await pollux.run_many(prompts=[], config=cfg)

    assert result["status"] == "ok"
    assert result["answers"] == []
    assert result["metrics"]["n_calls"] == 0


@pytest.mark.asyncio
async def test_run_without_source_succeeds() -> None:
    """run() with prompt-only (no source) should work."""
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    result = await pollux.run("What is 2+2?", config=cfg)

    assert result["status"] == "ok"
    assert len(result["answers"]) == 1


@pytest.mark.asyncio
async def test_api_error_includes_phase_provider_and_call_idx_for_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Executor should attach stable context fields to provider API errors."""

    @dataclass
    class FailingSecondCallProvider(FakeProvider):
        async def generate(self, **kwargs: Any) -> dict[str, Any]:
            parts = kwargs.get("parts", [])
            prompt = parts[-1] if parts and isinstance(parts[-1], str) else ""
            if prompt == "Q2":
                raise APIError(
                    "bad request",
                    retryable=False,
                    status_code=400,
                    provider="gemini",
                    phase="generate",
                )
            return {"text": "ok", "usage": {"total_token_count": 1}}

    fake = FailingSecondCallProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    cfg = Config(
        provider="gemini",
        model="gemini-2.0-flash",
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
async def test_api_error_includes_phase_provider_and_call_idx_for_upload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Upload failures should be marked as phase='upload' with call_idx."""

    @dataclass
    class FailingUploadProvider(FakeProvider):
        async def upload_file(self, path: Any, mime_type: str) -> str:
            _ = path, mime_type
            raise APIError(
                "upload failed",
                retryable=False,
                provider="openai",
                phase="upload",
            )

    fake = FailingUploadProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello")

    cfg = Config(
        provider="openai",
        model="gpt-4o-mini",
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
async def test_api_error_includes_phase_and_provider_for_cache_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache creation failures should be marked as phase='cache'."""

    @dataclass
    class FailingCacheProvider(FakeProvider):
        async def create_cache(self, **kwargs: Any) -> str:
            _ = kwargs
            raise APIError(
                "cache failed",
                retryable=False,
                provider="gemini",
                phase="cache",
            )

    fake = FailingCacheProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    cfg = Config(
        provider="gemini",
        model="cache-model",
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
    """Provider cleanup should run after successful execution."""

    @dataclass
    class _ClosableProvider(FakeProvider):
        closed: int = 0

        async def aclose(self) -> None:
            self.closed += 1

    fake = _ClosableProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    result = await pollux.run_many(("Q1", "Q2"), config=cfg)

    assert result["status"] == "ok"
    assert fake.closed == 1


@pytest.mark.asyncio
async def test_provider_close_error_does_not_mask_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup failures should never turn a success into an error."""

    @dataclass
    class _FailingCloseProvider(FakeProvider):
        closed: int = 0

        async def aclose(self) -> None:
            self.closed += 1
            raise RuntimeError("close failed")

    fake = _FailingCloseProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    result = await pollux.run("Q", config=cfg)

    assert result["status"] == "ok"
    assert fake.closed == 1


@pytest.mark.asyncio
async def test_provider_close_error_does_not_mask_primary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup should not replace the primary exception from execution."""

    @dataclass
    class _FailingGenerateClosableProvider(FakeProvider):
        closed: int = 0

        async def generate(self, **_kwargs: Any) -> dict[str, Any]:
            raise APIError("bad request", retryable=False, status_code=400)

        async def aclose(self) -> None:
            self.closed += 1
            raise RuntimeError("close failed")

    fake = _FailingGenerateClosableProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    with pytest.raises(APIError, match="bad request"):
        await pollux.run("Q", config=cfg)

    assert fake.closed == 1


# =============================================================================
# Retry Behavior (Boundary)
# =============================================================================


@pytest.mark.asyncio
async def test_retry_replays_generate_on_retryable_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry should replay provider.generate() on retryable failures."""

    @dataclass
    class FlakyGenerateProvider(FakeProvider):
        generate_calls: int = 0

        async def generate(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            self.generate_calls += 1
            if self.generate_calls == 1:
                raise APIError("rate limited", retryable=True, status_code=429)
            return {"text": "ok", "usage": {"total_token_count": 1}}

    fake = FlakyGenerateProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(
        provider="gemini",
        model="gemini-2.0-flash",
        use_mock=True,
        retry=RetryPolicy(
            max_attempts=2,
            initial_delay_s=0.0,
            max_delay_s=0.0,
            jitter=False,
        ),
    )

    result = await pollux.run("hello", config=cfg)

    assert result["answers"] == ["ok"]
    assert fake.generate_calls == 2


@pytest.mark.asyncio
async def test_retry_does_not_replay_non_retryable_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry should not replay when provider error is not retryable."""

    @dataclass
    class FailingProvider(FakeProvider):
        generate_calls: int = 0

        async def generate(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            self.generate_calls += 1
            raise APIError("bad request", retryable=False, status_code=400)

    fake = FailingProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(
        provider="gemini",
        model="gemini-2.0-flash",
        use_mock=True,
        retry=RetryPolicy(
            max_attempts=3,
            initial_delay_s=0.0,
            max_delay_s=0.0,
            jitter=False,
        ),
    )

    with pytest.raises(APIError):
        await pollux.run("hello", config=cfg)

    assert fake.generate_calls == 1


@pytest.mark.asyncio
async def test_retry_replays_upload_on_retryable_api_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Retry should replay provider.upload_file() on explicit retry signals."""

    @dataclass
    class FlakyUploadProvider(FakeProvider):
        upload_attempts: int = 0

        async def upload_file(self, path: Any, mime_type: str) -> str:
            _ = path, mime_type
            self.upload_attempts += 1
            if self.upload_attempts == 1:
                raise APIError(
                    "rate limited",
                    retryable=True,
                    status_code=429,
                    retry_after_s=0.0,
                )
            return "mock://uploaded/doc.txt"

        async def generate(self, **kwargs: Any) -> dict[str, Any]:
            parts = kwargs.get("parts", [])
            assert any(
                isinstance(p, dict) and p.get("uri") == "mock://uploaded/doc.txt"
                for p in parts
            )
            return {"text": "ok", "usage": {"total_token_count": 1}}

    fake = FlakyUploadProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello")

    cfg = Config(
        provider="gemini",
        model="gemini-2.0-flash",
        use_mock=True,
        retry=RetryPolicy(
            max_attempts=2,
            initial_delay_s=0.0,
            max_delay_s=0.0,
            jitter=False,
        ),
    )

    result = await pollux.run(
        "Read this",
        source=Source.from_file(file_path),
        config=cfg,
    )

    assert result["answers"] == ["ok"]
    assert fake.upload_attempts == 2


@pytest.mark.asyncio
async def test_retry_does_not_replay_upload_without_status_or_retry_after(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Uploads are side-effectful; avoid retrying ambiguous failures by default."""

    @dataclass
    class AmbiguousUploadProvider(FakeProvider):
        upload_attempts: int = 0

        async def upload_file(self, path: Any, mime_type: str) -> str:
            _ = path, mime_type
            self.upload_attempts += 1
            raise APIError(
                "upload timed out",
                provider="gemini",
                phase="upload",
            )

        async def generate(self, **_kwargs: Any) -> dict[str, Any]:
            raise AssertionError("generate() should not be reached when upload fails")

    fake = AmbiguousUploadProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello")

    cfg = Config(
        provider="gemini",
        model="gemini-2.0-flash",
        use_mock=True,
        retry=RetryPolicy(
            max_attempts=2,
            initial_delay_s=0.0,
            max_delay_s=0.0,
            jitter=False,
        ),
    )

    with pytest.raises(APIError):
        await pollux.run(
            "Read this",
            source=Source.from_file(file_path),
            config=cfg,
        )

    assert fake.upload_attempts == 1


# =============================================================================
# Source Factory: Error Paths
# =============================================================================


def test_source_from_file_rejects_missing_file(tmp_path: Any) -> None:
    """from_file() should fail clearly for non-existent paths."""
    missing = tmp_path / "does_not_exist.txt"

    with pytest.raises(SourceError) as exc:
        Source.from_file(missing)

    assert "not found" in str(exc.value).lower()


@pytest.mark.parametrize("invalid_ref", ["", "   "])
def test_source_from_arxiv_rejects_invalid_refs(invalid_ref: str) -> None:
    """from_arxiv() should fail for empty/whitespace strings."""
    with pytest.raises(SourceError):
        Source.from_arxiv(invalid_ref)


def test_source_from_youtube_creates_valid_source() -> None:
    """from_youtube() should return a valid Source with correct attributes."""
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    source = Source.from_youtube(url)

    assert source.source_type == "youtube"
    assert source.identifier == url
    assert source.mime_type == "video/mp4"
    assert source.size_bytes == 0  # Placeholder until fetched


def test_source_from_uri_creates_valid_source() -> None:
    """from_uri() should return a valid Source with correct attributes."""
    uri = "gs://my-bucket/data/document.pdf"
    source = Source.from_uri(uri, mime_type="application/pdf")

    assert source.source_type == "uri"
    assert source.identifier == uri
    assert source.mime_type == "application/pdf"
    assert source.size_bytes == 0


def test_source_from_uri_uses_default_mime_type() -> None:
    """from_uri() should default to application/octet-stream."""
    source = Source.from_uri("https://example.com/file")

    assert source.mime_type == "application/octet-stream"


# =============================================================================
# Pipeline Internals
# =============================================================================


@pytest.mark.asyncio
async def test_cache_creation_is_single_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent identical requests should create one cache entry."""
    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    # Keep this deterministic and isolated from other tests without relying on
    # CacheRegistry private attributes.
    monkeypatch.setattr(pollux, "_registry", CacheRegistry())

    cfg = Config(
        provider="gemini",
        model="cache-model",
        use_mock=True,
        enable_caching=True,
    )
    source = Source.from_text("cache me", identifier="same-id")

    await asyncio.gather(
        pollux.run_many(("A",), sources=(source,), config=cfg),
        pollux.run_many(("B",), sources=(source,), config=cfg),
    )

    assert fake.cache_calls == 1


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
        model="cache-model",
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

    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)
    await pollux.run_many(
        ("Read this",), sources=(Source.from_file(file_path),), config=cfg
    )

    assert fake.upload_calls == 1
    assert fake.last_parts is not None
    assert not any(isinstance(p, dict) and "file_path" in p for p in fake.last_parts)
    assert any(
        isinstance(p, dict) and isinstance(p.get("uri"), str) for p in fake.last_parts
    )


@pytest.mark.asyncio
async def test_concurrent_calls_share_file_upload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Concurrent prompt calls should upload a shared file once."""

    @dataclass
    class SlowUploadProvider(FakeProvider):
        async def upload_file(self, path: Any, mime_type: str) -> str:
            del mime_type
            self.upload_calls += 1
            await asyncio.sleep(0.02)
            return f"mock://uploaded/{path.name}"

    fake = SlowUploadProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    file_path = tmp_path / "shared.pdf"
    file_path.write_bytes(b"%PDF-1.4 fake")

    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)
    await pollux.run_many(
        prompts=("Q1", "Q2"),
        sources=(Source.from_file(file_path, mime_type="application/pdf"),),
        config=cfg,
    )

    assert fake.upload_calls == 1


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
        model="gemini-2.0-flash",
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


@pytest.mark.asyncio
async def test_cached_context_is_not_resent_on_each_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When cache is active, call payloads should include only prompt-specific parts."""

    @dataclass
    class PartsCaptureProvider(FakeProvider):
        received_parts: list[list[Any]] = field(default_factory=list)
        cache_names: list[str | None] = field(default_factory=list)

        async def generate(
            self,
            *,
            model: str,
            parts: list[Any],
            system_instruction: str | None = None,
            cache_name: str | None = None,
            response_schema: dict[str, Any] | None = None,
            reasoning_effort: str | None = None,
            history: list[dict[str, str]] | None = None,
            delivery_mode: str = "realtime",
            previous_response_id: str | None = None,
        ) -> dict[str, Any]:
            del (
                model,
                system_instruction,
                response_schema,
                reasoning_effort,
                history,
                delivery_mode,
                previous_response_id,
            )
            self.received_parts.append(parts)
            self.cache_names.append(cache_name)
            prompt = parts[-1] if parts and isinstance(parts[-1], str) else ""
            return {"text": f"ok:{prompt}", "usage": {"total_token_count": 1}}

    fake = PartsCaptureProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    monkeypatch.setattr(pollux, "_registry", CacheRegistry())

    cfg = Config(
        provider="gemini",
        model="cache-model",
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
    """Regression: same identifier+size but different content must not collide."""
    source_a = Source.from_text("AAAA", identifier="same")
    source_b = Source.from_text("BBBB", identifier="same")

    key_a = compute_cache_key("gemini-2.0-flash", (source_a,))
    key_b = compute_cache_key("gemini-2.0-flash", (source_b,))

    assert key_a != key_b


def test_cache_identity_distinguishes_youtube_urls() -> None:
    """Different YouTube URLs should never share the same cache key."""
    source_a = Source.from_youtube("https://www.youtube.com/watch?v=video-a")
    source_b = Source.from_youtube("https://www.youtube.com/watch?v=video-b")

    key_a = compute_cache_key("gemini-2.0-flash", (source_a,))
    key_b = compute_cache_key("gemini-2.0-flash", (source_b,))

    assert key_a != key_b


def test_cache_identity_distinguishes_uri_sources() -> None:
    """Different URI sources should never share the same cache key."""
    source_a = Source.from_uri("https://example.com/a.pdf", mime_type="application/pdf")
    source_b = Source.from_uri("https://example.com/b.pdf", mime_type="application/pdf")

    key_a = compute_cache_key("gemini-2.0-flash", (source_a,))
    key_b = compute_cache_key("gemini-2.0-flash", (source_b,))

    assert key_a != key_b


def test_cache_registry_expires_stale_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cache entries should be evicted after TTL expires."""
    import pollux.cache as cache_module
    from pollux.cache import CacheRegistry

    registry = CacheRegistry()
    fake_time = [1000.0]  # Mutable container for closure

    monkeypatch.setattr(cache_module.time, "time", lambda: fake_time[0])  # type: ignore[attr-defined]

    # Set entry with 60 second TTL
    registry.set("key", "cachedContents/abc", ttl_seconds=60)

    # Entry exists before expiration
    assert registry.get("key") == "cachedContents/abc"

    # Advance time past expiration
    fake_time[0] = 1061.0

    # Entry should be evicted
    assert registry.get("key") is None


def test_cache_registry_handles_zero_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero TTL entries should expire immediately on next get."""
    import pollux.cache as cache_module
    from pollux.cache import CacheRegistry

    registry = CacheRegistry()
    monkeypatch.setattr(cache_module.time, "time", lambda: 1000.0)  # type: ignore[attr-defined]

    registry.set("key", "cachedContents/xyz", ttl_seconds=0)

    # Expire time is exactly current_time (1000 + 0 = 1000)
    # get() checks if time.time() >= expires_at, so it should expire
    assert registry.get("key") is None


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("1706.03762", "https://arxiv.org/pdf/1706.03762.pdf"),
        ("https://arxiv.org/abs/1706.03762", "https://arxiv.org/pdf/1706.03762.pdf"),
        (
            "https://arxiv.org/pdf/1706.03762.pdf",
            "https://arxiv.org/pdf/1706.03762.pdf",
        ),
        ("cs.CL/9901001", "https://arxiv.org/pdf/cs.CL/9901001.pdf"),
    ],
)
def test_source_from_arxiv_normalizes_to_canonical_pdf_url(
    ref: str, expected: str
) -> None:
    """arXiv refs should normalize to a canonical PDF URL."""
    source = Source.from_arxiv(ref)

    assert source.source_type == "arxiv"
    assert source.identifier == expected
    assert source.mime_type == "application/pdf"
    assert source.content_loader() == expected.encode("utf-8")


def test_source_from_arxiv_rejects_non_arxiv_urls() -> None:
    """Only arxiv.org URLs should be accepted."""
    with pytest.raises(SourceError):
        Source.from_arxiv("https://example.com/abs/1706.03762")


@pytest.mark.asyncio
async def test_options_response_schema_requires_provider_capability() -> None:
    """Strict capability checks reject unsupported structured outputs."""
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)
    with pytest.raises(ConfigurationError, match="structured outputs"):
        await pollux.run(
            "Extract fields",
            config=cfg,
            options=Options(response_schema={"type": "object"}),
        )


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
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    await pollux.run_many(
        ("Q1?",),
        sources=(Source.from_text("context"),),
        config=cfg,
        options=Options(
            response_schema=ExampleSchema,
            reasoning_effort="high",
            delivery_mode="realtime",
        ),
    )

    assert fake.last_generate_kwargs is not None
    assert fake.last_generate_kwargs["reasoning_effort"] == "high"
    assert fake.last_generate_kwargs["delivery_mode"] == "realtime"
    assert fake.last_generate_kwargs["history"] is None
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
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

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

        async def generate(
            self,
            *,
            model: str,
            parts: list[Any],
            system_instruction: str | None = None,
            cache_name: str | None = None,
            response_schema: dict[str, Any] | None = None,
            reasoning_effort: str | None = None,
            history: list[dict[str, str]] | None = None,
            delivery_mode: str = "realtime",
            previous_response_id: str | None = None,
        ) -> dict[str, Any]:
            _ = (
                model,
                parts,
                system_instruction,
                cache_name,
                reasoning_effort,
                history,
                delivery_mode,
                previous_response_id,
            )
            assert isinstance(response_schema, dict)
            return {
                "text": '{"title":"A","findings":["x","y"]}',
                "structured": {"title": "A", "findings": ["x", "y"]},
                "usage": {"total_token_count": 1},
            }

    fake = _StructuredProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

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
# Options Validation
# =============================================================================


def test_options_history_accepts_valid_message_shape() -> None:
    """History shape should be accepted so the API remains forward-compatible."""
    options = Options(history=[{"role": "user", "content": "hello"}])
    assert options.history == [{"role": "user", "content": "hello"}]


def test_options_continue_from_accepts_result_like_dict() -> None:
    """continue_from shape should be accepted for future rollout."""
    previous: ResultEnvelope = {"status": "ok", "answers": ["x"]}
    options = Options(continue_from=previous)
    assert options.continue_from == previous


def test_options_rejects_invalid_history_items() -> None:
    """Invalid history item shapes should fail fast with a clear error."""
    bad_history: Any = [{"role": "user", "content": 123}]
    with pytest.raises(ConfigurationError, match="history items"):
        Options(history=bad_history)


def test_options_rejects_history_and_continue_from_together() -> None:
    """Conversation inputs are mutually exclusive."""
    previous: ResultEnvelope = {"status": "ok", "answers": ["x"]}
    with pytest.raises(ConfigurationError, match="mutually exclusive"):
        Options(
            history=[{"role": "user", "content": "hello"}],
            continue_from=previous,
        )


def test_options_rejects_invalid_response_schema_type() -> None:
    """response_schema must be a BaseModel subclass or JSON schema dict."""
    with pytest.raises(ConfigurationError, match="response_schema"):
        Options(response_schema="not-a-schema")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_conversation_options_are_lifecycle_gated_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conversation options should fail fast until lifecycle gate is opened."""
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
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    with pytest.raises(ConfigurationError, match="reserved for a future release"):
        await pollux.run_many(
            ("Q1?",),
            config=cfg,
            options=Options(history=[{"role": "user", "content": "hello"}]),
        )


@pytest.mark.asyncio
async def test_conversation_options_can_be_enabled_for_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle gate should allow conversation options when explicitly enabled."""
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
    monkeypatch.setenv("POLLUX_EXPERIMENTAL_CONVERSATION", "1")
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    await pollux.run_many(
        ("Q1?",),
        config=cfg,
        options=Options(history=[{"role": "user", "content": "hello"}]),
    )

    assert fake.last_generate_kwargs is not None
    assert fake.last_generate_kwargs["history"] == [
        {"role": "user", "content": "hello"}
    ]


@pytest.mark.asyncio
async def test_continue_from_requires_conversation_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """continue_from must contain _conversation_state once conversation is enabled."""
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
    monkeypatch.setenv("POLLUX_EXPERIMENTAL_CONVERSATION", "1")
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    with pytest.raises(ConfigurationError, match="missing _conversation_state"):
        await pollux.run_many(
            ("Q1?",),
            config=cfg,
            options=Options(continue_from={"status": "ok", "answers": ["x"]}),
        )


@pytest.mark.asyncio
async def test_continue_from_derives_history_and_previous_response_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """continue_from should supply history + previous_response_id to provider.generate()."""
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
    monkeypatch.setenv("POLLUX_EXPERIMENTAL_CONVERSATION", "1")
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

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
    assert fake.generate_kwargs[0]["history"] == [{"role": "user", "content": "hello"}]
    assert fake.generate_kwargs[0]["previous_response_id"] == "resp_123"


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

    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)
    with pytest.raises(PlanningError, match="Failed to load content"):
        await pollux.run_many(
            ("Q",),
            sources=(bad,),
            config=cfg,
        )


@pytest.mark.asyncio
async def test_result_status_is_partial_when_some_answers_are_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Status classification should be stable across refactors."""
    fake = ScriptedProvider(
        script=[
            {"text": "ok", "usage": {"total_token_count": 1}},
            {"text": "", "usage": {"total_token_count": 1}},
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    result = await pollux.run_many(("A", "B"), config=cfg)

    assert result["status"] == "partial"
    assert result["answers"] == ["ok", ""]


@pytest.mark.asyncio
async def test_result_status_is_error_when_all_answers_are_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-empty answers should produce status='error' (not ok/partial)."""
    fake = ScriptedProvider(
        script=[
            {"text": "", "usage": {"total_token_count": 1}},
            {"text": "", "usage": {"total_token_count": 1}},
        ]
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    result = await pollux.run_many(("A", "B"), config=cfg)

    assert result["status"] == "error"
    assert result["answers"] == ["", ""]


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
            {
                "text": '{"title":"A"}',
                "structured": {"title": "A"},
                "usage": {"total_token_count": 1},
            }
        ],
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    result = await pollux.run(
        "Extract",
        config=cfg,
        options=Options(response_schema=Paper),
    )

    assert result["answers"] == ['{"title":"A"}']
    assert result["structured"] == [None]
