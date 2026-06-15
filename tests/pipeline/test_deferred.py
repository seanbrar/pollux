"""Pipeline boundary tests."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel
import pytest

import pollux
import pollux.cache
from pollux.cache import CacheHandle
from pollux.config import Config
from pollux.deferred import DeferredHandle
from pollux.errors import (
    ConfigurationError,
    DeferredNotReadyError,
)
from pollux.options import Options
from pollux.providers.anthropic import AnthropicProvider
from pollux.providers.base import (
    ProviderDeferredItem,
)
from pollux.providers.gemini import GeminiProvider
from pollux.providers.openai import OpenAIProvider
from pollux.source import Source
from tests.conftest import (
    ANTHROPIC_MODEL,
    GEMINI_MODEL,
    OPENAI_MODEL,
)
from tests.helpers import InMemoryDeferredProvider, RejectingValidatingDeferredProvider

pytestmark = pytest.mark.integration


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
