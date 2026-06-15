"""Pipeline boundary tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

import pollux
import pollux.cache
from pollux.cache import CacheHandle, CacheRegistry, compute_cache_key
from pollux.config import Config
from pollux.errors import (
    APIError,
    ConfigurationError,
)
from pollux.options import Options
from pollux.providers.base import (
    ProviderCapabilities,
)
from pollux.providers.models import (
    ProviderFileAsset,
    ProviderRequest,
    ProviderResponse,
)
from pollux.retry import RetryPolicy
from pollux.source import Source
from tests.conftest import (
    CACHE_MODEL,
    GEMINI_MODEL,
    LOCAL_MODEL,
    OPENAI_MODEL,
    FakeProvider,
)
from tests.helpers import GateProvider, RejectingValidatingProvider

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_cache_diagnostics_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that cache_mode and cache_hit are correctly populated in ResultEnvelope metrics."""
    from pollux.providers.base import ProviderCapabilities

    fake = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=False,
            implicit_caching=True,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    cfg = Config(provider="openai", model=OPENAI_MODEL, use_mock=True)

    # 1. No caching
    # Need a separate provider for No-Implicit-Caching to avoid validation passing
    fake_no_caching = FakeProvider(
        _capabilities=ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=False,
            reasoning=False,
            deferred_delivery=False,
            conversation=False,
            implicit_caching=False,
        )
    )
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake_no_caching)
    res_none = await pollux.run("hello", config=cfg)
    assert res_none["metrics"]["cache_mode"] == "none"
    assert res_none["metrics"]["cache_hit"] is False

    # 2. Implicit caching
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)
    res_implicit = await pollux.run(
        "hello", config=cfg, options=Options(implicit_caching=True)
    )
    assert res_implicit["metrics"]["cache_mode"] == "implicit"
    # usage lacks cached_tokens here, so cache_hit is False
    assert res_implicit["metrics"]["cache_hit"] is False

    # 3. Persistent caching (using mock provider / plan cache name)
    @dataclass
    class _CacheTrackingProvider(FakeProvider):
        async def create_cache(self, **_kwargs: Any) -> str:
            return "cachedContents/mock-handle-123"

    fake_cache = _CacheTrackingProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake_cache)
    cfg_cache = Config(provider="gemini", model=CACHE_MODEL, use_mock=True)
    handle = await pollux.create_cache(
        (Source.from_text("shared context"),), config=cfg_cache
    )

    # Use the handle
    res_cached = await pollux.run(
        "hello", config=cfg_cache, options=Options(cache=handle)
    )
    assert res_cached["metrics"]["cache_mode"] == "persistent"
    assert res_cached["metrics"]["cache_hit"] is True


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
async def test_local_file_sources_raise_local_specific_guidance(tmp_path: Any) -> None:
    """Local file inputs should fail with the text-only local provider guidance."""
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello", encoding="utf-8")

    cfg = Config(
        provider="local",
        model=LOCAL_MODEL,
        base_url="http://localhost:8080/v1",
    )

    with pytest.raises(
        ConfigurationError, match="Provider does not support file or multimodal input"
    ) as exc:
        await pollux.run(
            "Summarize this.",
            source=Source.from_file(file_path, mime_type="text/plain"),
            config=cfg,
        )

    assert exc.value.hint is not None
    assert "Source.from_text()" in exc.value.hint


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
@pytest.mark.parametrize(
    ("conflict_options", "expected_match"),
    [
        ({"system_instruction": "Be brief."}, "system_instruction cannot be used"),
        (
            {
                "tools": [
                    {
                        "name": "f",
                        "description": "d",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ]
            },
            "tools cannot be used",
        ),
        ({"tool_choice": "auto"}, "tool_choice cannot be used"),
    ],
)
async def test_cached_context_rejects_conflicting_options(
    monkeypatch: pytest.MonkeyPatch,
    conflict_options: dict[str, Any],
    expected_match: str,
) -> None:
    """A cache handle conflicts with options the cache already bakes in."""
    import time

    fake = FakeProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    cfg = Config(provider="gemini", model=CACHE_MODEL, use_mock=True)
    handle = CacheHandle(
        name="cachedContents/test",
        model=CACHE_MODEL,
        provider="gemini",
        expires_at=time.time() + 3600,
    )

    with pytest.raises(ConfigurationError, match=expected_match):
        await pollux.run(
            "prompt",
            config=cfg,
            options=Options(cache=handle, **conflict_options),
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
