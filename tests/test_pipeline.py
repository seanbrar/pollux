"""Pipeline boundary tests for the simplified v1 execution flow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
import pytest

import pollux
from pollux.cache import compute_cache_key
from pollux.config import Config
from pollux.errors import ConfigurationError, SourceError
from pollux.options import Options
from pollux.providers.base import ProviderCapabilities
from pollux.request import normalize_request
from pollux.source import Source
from tests.conftest import FakeProvider

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
async def test_batch_returns_one_answer_per_prompt() -> None:
    """Vectorized prompts should produce one answer per prompt."""
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    result = await pollux.batch(
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
async def test_batch_with_empty_prompts_returns_empty_result() -> None:
    """Empty prompt list should return empty answers (idempotent behavior)."""
    cfg = Config(provider="gemini", model="gemini-2.0-flash", use_mock=True)

    result = await pollux.batch(prompts=[], config=cfg)

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

    # Keep this deterministic and isolated from other tests.
    pollux._registry._entries.clear()  # pyright: ignore[reportPrivateUsage]
    pollux._registry._inflight.clear()  # pyright: ignore[reportPrivateUsage]

    cfg = Config(
        provider="gemini",
        model="cache-model",
        use_mock=True,
        enable_caching=True,
    )
    source = Source.from_text("cache me", identifier="same-id")

    await asyncio.gather(
        pollux.batch(("A",), sources=(source,), config=cfg),
        pollux.batch(("B",), sources=(source,), config=cfg),
    )

    assert fake.cache_calls == 1


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
    await pollux.batch(
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
    await pollux.batch(
        prompts=("Q1", "Q2"),
        sources=(Source.from_file(file_path, mime_type="application/pdf"),),
        config=cfg,
    )

    assert fake.upload_calls == 1


@pytest.mark.asyncio
async def test_cached_context_is_not_resent_on_each_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When cache is active, call payloads should include only prompt-specific parts."""

    @dataclass
    class CaptureProvider(FakeProvider):
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

    fake = CaptureProvider()
    monkeypatch.setattr(pollux, "_get_provider", lambda _config: fake)

    pollux._registry._entries.clear()  # pyright: ignore[reportPrivateUsage]
    pollux._registry._inflight.clear()  # pyright: ignore[reportPrivateUsage]

    cfg = Config(
        provider="gemini",
        model="cache-model",
        use_mock=True,
        enable_caching=True,
    )
    await pollux.batch(
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
    assert "key" not in registry._entries  # Verify it was deleted


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

    await pollux.batch(
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
        await pollux.batch(
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
    previous = {"status": "ok", "answers": ["x"]}
    options = Options(continue_from=previous)  # type: ignore[arg-type]
    assert options.continue_from == previous


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
        await pollux.batch(
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

    await pollux.batch(
        ("Q1?",),
        config=cfg,
        options=Options(history=[{"role": "user", "content": "hello"}]),
    )

    assert fake.last_generate_kwargs is not None
    assert fake.last_generate_kwargs["history"] == [
        {"role": "user", "content": "hello"}
    ]
