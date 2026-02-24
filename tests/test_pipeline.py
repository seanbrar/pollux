"""Pipeline boundary tests for the simplified v1 execution flow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hypothesis import given, settings
from hypothesis import strategies as st
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
            return {"text": "ok", "usage": {"total_tokens": 1}}

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
        async def upload_file(self, path: Any, mime_type: str) -> str:
            _ = path, mime_type
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

        async def generate(self, **kwargs: Any) -> dict[str, Any]:
            if self.fail_generate:
                raise APIError("bad request", retryable=False, status_code=400)
            return await super().generate(**kwargs)

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

        async def generate(self, **kwargs: Any) -> dict[str, Any]:
            self.generate_calls += 1
            if self.mode == "generate_retry" and self.generate_calls == 1:
                raise APIError("rate limited", retryable=True, status_code=429)
            if self.mode == "generate_no_retry":
                raise APIError("bad request", retryable=False, status_code=400)

            # Upload scenarios: verify substitution happened before generate().
            if self.mode.startswith("upload_"):
                parts = kwargs.get("parts", [])
                assert any(
                    isinstance(p, dict) and p.get("uri") == "mock://uploaded/doc.txt"
                    for p in parts
                )
            return {"text": "ok", "usage": {"total_tokens": 1}}

        async def upload_file(self, path: Any, mime_type: str) -> str:
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
            return "mock://uploaded/doc.txt"

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
        isinstance(p, dict) and isinstance(p.get("uri"), str) for p in fake.last_parts
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
            temperature: float | None = None,
            top_p: float | None = None,
            tools: list[dict[str, Any]] | None = None,
            tool_choice: Any | None = None,
            reasoning_effort: str | None = None,
            history: list[dict[str, str]] | None = None,
            delivery_mode: str = "realtime",
            previous_response_id: str | None = None,
        ) -> dict[str, Any]:
            del (
                model,
                system_instruction,
                response_schema,
                temperature,
                top_p,
                tools,
                tool_choice,
                reasoning_effort,
                history,
                delivery_mode,
                previous_response_id,
            )
            self.received_parts.append(parts)
            self.cache_names.append(cache_name)
            prompt = parts[-1] if parts and isinstance(parts[-1], str) else ""
            return {"text": f"ok:{prompt}", "usage": {"total_tokens": 1}}

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


@given(
    arxiv_id=st.one_of(
        st.from_regex(r"\d{4}\.\d{4,5}(?:v\d+)?", fullmatch=True),
        st.from_regex(
            r"[a-z\-]+(?:\.[a-z\-]+)?/\d{7}(?:v\d+)?",
            fullmatch=True,
        ),
    )
)
@settings(max_examples=10, deadline=None, derandomize=True)
def test_source_from_arxiv_normalizes_to_canonical_pdf_url(arxiv_id: str) -> None:
    """Property: arXiv refs normalize to canonical PDF URLs and stable loaders."""
    expected = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    refs = [
        arxiv_id,
        f"https://arxiv.org/abs/{arxiv_id}",
        f"https://arxiv.org/pdf/{arxiv_id}.pdf",
    ]
    for ref in refs:
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
    assert fake.last_generate_kwargs["delivery_mode"] == "realtime"
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

        async def generate(
            self,
            *,
            model: str,
            parts: list[Any],
            system_instruction: str | None = None,
            cache_name: str | None = None,
            response_schema: dict[str, Any] | None = None,
            temperature: float | None = None,
            top_p: float | None = None,
            tools: list[dict[str, Any]] | None = None,
            tool_choice: Any | None = None,
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
                temperature,
                top_p,
                tools,
                tool_choice,
                reasoning_effort,
                history,
                delivery_mode,
                previous_response_id,
            )
            assert isinstance(response_schema, dict)
            return {
                "text": '{"title":"A","findings":["x","y"]}',
                "structured": {"title": "A", "findings": ["x", "y"]},
                "usage": {"total_tokens": 1},
            }

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
        {"role": "user", "content": "hello"}
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
    assert fake.generate_kwargs[0]["history"] == [{"role": "user", "content": "hello"}]
    assert fake.generate_kwargs[0]["previous_response_id"] == "resp_123"


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

        async def generate(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {
                "text": "Assistant reply.",
                "usage": {"total_tokens": 1},
                "response_id": "resp_next",
            }

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
                "usage": {"total_tokens": 1},
            }
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

        async def generate(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {
                "text": "",
                "usage": {"total_tokens": 1},
                "tool_calls": [
                    {"id": "call_1", "name": "get_weather", "arguments": "{}"}
                ],
            }

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
    received_history = fake.generate_kwargs[0]["history"]
    assert len(received_history) == 3
    # Verify tool message was preserved (not filtered out)
    assert received_history[2]["role"] == "tool"
    assert received_history[2]["tool_call_id"] == "call_1"
    # Verify assistant tool_calls preserved
    assert received_history[1]["tool_calls"] is not None


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
