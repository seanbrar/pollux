"""Provider contract characterization tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from typing import TYPE_CHECKING, Any

import pytest

from pollux.errors import APIError, ConfigurationError
from pollux.interaction.input import Input
from pollux.providers import gemini as gemini_module
from pollux.providers.anthropic import AnthropicProvider
from pollux.providers.base import ProviderDeferredHandle, ProviderDeferredItem
from pollux.providers.gemini import GeminiProvider
from pollux.providers.openai import OpenAIProvider
from pollux.source import Source
from tests.conftest import (
    ANTHROPIC_MODEL,
    GEMINI_MODEL,
    OPENAI_MODEL,
)
from tests.helpers import make_interaction

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.contract


# =============================================================================
# OpenAI Deferred Delivery (Characterization)
# =============================================================================


class _FakeBatchFilesClient:
    """Captures OpenAI Files API interactions for batch tests."""

    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []
        self.contents: dict[str, str] = {}
        self.deleted_file_ids: list[str] = []

    async def create(self, **kwargs: Any) -> Any:
        self.create_calls.append(kwargs)
        purpose = kwargs["purpose"]
        if purpose == "user_data":
            return type("File", (), {"id": "file_uploaded_pdf"})()
        return type("File", (), {"id": "file_batch_input"})()

    async def retrieve_content(self, file_id: str) -> str:
        return self.contents[file_id]

    async def delete(self, file_id: str) -> None:
        self.deleted_file_ids.append(file_id)


class _FakeBatchesClient:
    """Captures OpenAI Batch API interactions for batch tests."""

    def __init__(self) -> None:
        self.create_kwargs: dict[str, Any] | None = None
        self.retrieve_result: Any = None
        self.cancelled_job_id: str | None = None
        self.cancel_result: Any = None

    async def create(self, **kwargs: Any) -> Any:
        self.create_kwargs = kwargs
        return type(
            "Batch",
            (),
            {"id": "batch_123", "created_at": 1_700_000_000},
        )()

    async def retrieve(self, job_id: str) -> Any:
        _ = job_id
        return self.retrieve_result

    async def cancel(self, job_id: str) -> Any:
        self.cancelled_job_id = job_id
        if self.cancel_result is not None:
            return self.cancel_result
        return type("Batch", (), {"id": job_id, "status": "cancelling"})()


@pytest.mark.asyncio
async def test_openai_submit_deferred_characterizes_batch_request(
    tmp_path: Path,
) -> None:
    """Deferred submission should upload JSONL and create a `/v1/responses` batch."""
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    files = _FakeBatchFilesClient()
    batches = _FakeBatchesClient()
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    snapshot, _, requirements, config = make_interaction(
        provider="openai",
        model=OPENAI_MODEL,
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
        },
        reasoning_effort="high",
        content="prompt",
    )
    snapshot = replace(
        snapshot, sources=(Source.from_file(pdf_path, mime_type="application/pdf"),)
    )
    inputs = [
        Input(content="Summarize this"),
        Input(content="Answer the question"),
    ]

    handle = await provider.submit_deferred(
        snapshot,
        inputs,
        requirements,
        config,
        request_ids=["pollux-000000", "pollux-000001"],
    )

    assert handle.job_id == "batch_123"
    assert handle.submitted_at == 1_700_000_000
    assert handle.provider_state == {
        "request_ids": ["pollux-000000", "pollux-000001"],
        "owned_file_ids": ["file_batch_input", "file_uploaded_pdf"],
    }

    assert len(files.create_calls) == 2
    assert files.create_calls[0]["purpose"] == "user_data"
    assert files.create_calls[1]["purpose"] == "batch"

    batch_upload = files.create_calls[1]["file"]
    payload = batch_upload.getvalue().decode("utf-8")
    lines = [json.loads(line) for line in payload.splitlines()]
    assert [line["custom_id"] for line in lines] == ["pollux-000000", "pollux-000001"]
    assert all(line["method"] == "POST" for line in lines)
    assert all(line["url"] == "/v1/responses" for line in lines)

    first_body = lines[0]["body"]
    assert first_body["model"] == OPENAI_MODEL
    assert first_body["text"]["format"]["type"] == "json_schema"

    second_body = lines[1]["body"]
    assert second_body["reasoning"] == {"effort": "high", "summary": "auto"}
    assert second_body["input"][0]["content"][0] == {
        "type": "input_file",
        "file_id": "file_uploaded_pdf",
    }

    assert batches.create_kwargs == {
        "input_file_id": "file_batch_input",
        "endpoint": "/v1/responses",
        "completion_window": "24h",
        "metadata": {
            "pollux_request_count": "2",
            "pollux_has_response_schema": "1",
        },
    }


@pytest.mark.asyncio
async def test_openai_submit_deferred_reuses_shared_file_uploads(
    tmp_path: Path,
) -> None:
    """Deferred fan-out should upload a shared local file once per batch."""
    pdf_path = tmp_path / "shared.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    files = _FakeBatchFilesClient()
    batches = _FakeBatchesClient()
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    snapshot, _, requirements, config = make_interaction(
        provider="openai",
        model=OPENAI_MODEL,
        content="prompt",
    )
    snapshot = replace(
        snapshot, sources=(Source.from_file(pdf_path, mime_type="application/pdf"),)
    )
    inputs = [
        Input(content="Question 1"),
        Input(content="Question 2"),
    ]

    await provider.submit_deferred(
        snapshot,
        inputs,
        requirements,
        config,
        request_ids=["pollux-000000", "pollux-000001"],
    )

    assert len(files.create_calls) == 2
    assert [call["purpose"] for call in files.create_calls] == ["user_data", "batch"]

    batch_upload = files.create_calls[1]["file"]
    lines = [json.loads(line) for line in batch_upload.getvalue().decode().splitlines()]

    first_file = lines[0]["body"]["input"][0]["content"][0]["file_id"]
    second_file = lines[1]["body"]["input"][0]["content"][0]["file_id"]
    assert first_file == "file_uploaded_pdf"
    assert second_file == first_file


@pytest.mark.asyncio
async def test_openai_submit_deferred_rejects_reasoning_budget_tokens_before_upload(
    tmp_path: Path,
) -> None:
    """Unsupported reasoning budgets should fail before deferred uploads begin."""
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    files = _FakeBatchFilesClient()
    batches = _FakeBatchesClient()
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    snapshot, _, requirements, config = make_interaction(
        provider="openai",
        model=OPENAI_MODEL,
        reasoning_budget_tokens=0,
        content="prompt",
    )
    snapshot = replace(
        snapshot, sources=(Source.from_file(pdf_path, mime_type="application/pdf"),)
    )
    inputs = [Input(content="Question")]

    with pytest.raises(
        ConfigurationError, match="Provider does not support reasoning_budget_tokens"
    ):
        await provider.submit_deferred(
            snapshot,
            inputs,
            requirements,
            config,
            request_ids=["pollux-000000"],
        )

    assert files.create_calls == []
    assert batches.create_kwargs is None


@pytest.mark.asyncio
async def test_openai_submit_deferred_preserves_remote_artifacts_on_failure(
    tmp_path: Path,
) -> None:
    """Submit failures should not assume rollback safety after remote side effects."""
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    files = _FakeBatchFilesClient()
    batches = _FakeBatchesClient()

    async def _fail_create(**kwargs: Any) -> Any:
        batches.create_kwargs = kwargs
        raise RuntimeError("batch create failed")

    batches.create = _fail_create  # type: ignore[method-assign]

    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    snapshot, _, requirements, config = make_interaction(
        provider="openai",
        model=OPENAI_MODEL,
        content="prompt",
    )
    snapshot = replace(
        snapshot, sources=(Source.from_file(pdf_path, mime_type="application/pdf"),)
    )
    inputs = [Input(content="Question")]

    with pytest.raises(
        APIError, match="OpenAI batch submit failed: batch create failed"
    ):
        await provider.submit_deferred(
            snapshot,
            inputs,
            requirements,
            config,
            request_ids=["pollux-000000"],
        )

    assert files.deleted_file_ids == []


@pytest.mark.asyncio
async def test_openai_inspect_deferred_normalizes_status_and_counts() -> None:
    """OpenAI batch status should map into Pollux deferred snapshot semantics."""
    files = _FakeBatchFilesClient()
    batches = _FakeBatchesClient()
    batches.retrieve_result = type(
        "Batch",
        (),
        {
            "status": "completed",
            "request_counts": type(
                "Counts", (), {"total": 3, "completed": 2, "failed": 1}
            )(),
            "created_at": 1_700_000_000,
            "completed_at": 1_700_000_600,
            "expires_at": 1_700_086_400,
        },
    )()
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    snapshot = await provider.inspect_deferred(
        ProviderDeferredHandle(job_id="batch_123")
    )

    assert snapshot.status == "partial"
    assert snapshot.provider_status == "completed"
    assert snapshot.request_count == 3
    assert snapshot.succeeded == 2
    assert snapshot.failed == 1
    assert snapshot.pending == 0
    assert snapshot.submitted_at == 1_700_000_000
    assert snapshot.completed_at == 1_700_000_600
    assert snapshot.expires_at == 1_700_086_400


@pytest.mark.asyncio
async def test_openai_inspect_deferred_falls_back_to_metadata_for_total() -> None:
    """Early OpenAI batch states may need metadata to recover request count."""
    files = _FakeBatchFilesClient()
    batches = _FakeBatchesClient()
    batches.retrieve_result = {
        "status": "validating",
        "request_counts": None,
        "metadata": {"pollux_request_count": "4"},
        "created_at": 1_700_000_000,
    }
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    snapshot = await provider.inspect_deferred(
        ProviderDeferredHandle(job_id="batch_123")
    )

    assert snapshot.status == "queued"
    assert snapshot.request_count == 4
    assert snapshot.pending == 4


@pytest.mark.asyncio
async def test_openai_inspect_deferred_terminal_failure_zeroes_pending() -> None:
    """Terminal batch failures should not leave requests counted as pending."""
    files = _FakeBatchFilesClient()
    batches = _FakeBatchesClient()
    batches.retrieve_result = {
        "status": "failed",
        "request_counts": None,
        "metadata": {"pollux_request_count": "2"},
        "failed_at": 1_700_000_600,
    }
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    snapshot = await provider.inspect_deferred(
        ProviderDeferredHandle(job_id="batch_123")
    )

    assert snapshot.status == "failed"
    assert snapshot.request_count == 2
    assert snapshot.failed == 2
    assert snapshot.pending == 0


@pytest.mark.asyncio
async def test_openai_inspect_deferred_marks_cancelled_failed_mix_as_partial() -> None:
    """Cancelled batches with failed rows should preserve the mixed terminal status."""
    files = _FakeBatchFilesClient()
    batches = _FakeBatchesClient()
    batches.retrieve_result = {
        "status": "cancelled",
        "request_counts": {"total": 3, "completed": 0, "failed": 1},
        "cancelled_at": 1_700_000_600,
    }
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    snapshot = await provider.inspect_deferred(
        ProviderDeferredHandle(job_id="batch_123")
    )

    assert snapshot.status == "partial"
    assert snapshot.request_count == 3
    assert snapshot.succeeded == 0
    assert snapshot.failed == 3
    assert snapshot.pending == 0


@pytest.mark.asyncio
async def test_openai_inspect_deferred_cleans_up_owned_files_when_terminal() -> None:
    """Terminal inspection should cleanup provider-owned input files."""
    files = _FakeBatchFilesClient()
    batches = _FakeBatchesClient()
    batches.retrieve_result = {
        "status": "completed",
        "request_counts": {"total": 1, "completed": 1, "failed": 0},
        "completed_at": 1_700_000_600,
    }
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    await provider.inspect_deferred(
        ProviderDeferredHandle(
            job_id="batch_123",
            provider_state={
                "owned_file_ids": ["file_batch_input", "file_uploaded_pdf"]
            },
        )
    )

    assert files.deleted_file_ids == ["file_batch_input", "file_uploaded_pdf"]


@pytest.mark.asyncio
async def test_openai_collect_deferred_parses_output_and_error_files() -> None:
    """Batch collection should merge output and error JSONL files by request id."""
    files = _FakeBatchFilesClient()
    files.contents["file_out"] = "\n".join(
        [
            json.dumps(
                {
                    "custom_id": "pollux-000001",
                    "response": {
                        "status_code": 200,
                        "body": {
                            "id": "resp_1",
                            "status": "completed",
                            "output": [
                                {
                                    "type": "reasoning",
                                    "summary": [{"text": "Reasoned"}],
                                },
                                {
                                    "type": "message",
                                    "content": [
                                        {
                                            "type": "output_text",
                                            "text": '{"summary":"A"}',
                                        }
                                    ],
                                },
                            ],
                            "usage": {
                                "input_tokens": 1,
                                "output_tokens": 2,
                                "total_tokens": 3,
                            },
                        },
                    },
                    "error": None,
                }
            )
        ]
    )
    files.contents["file_err"] = "\n".join(
        [
            json.dumps(
                {
                    "custom_id": "pollux-000000",
                    "error": {
                        "code": "batch_expired",
                        "message": "Request expired before execution",
                    },
                }
            )
        ]
    )

    batches = _FakeBatchesClient()
    batches.retrieve_result = {
        "output_file_id": "file_out",
        "error_file_id": "file_err",
        "metadata": {"pollux_has_response_schema": "1"},
    }
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    items = await provider.collect_deferred(ProviderDeferredHandle(job_id="batch_123"))

    assert {item.request_id for item in items} == {"pollux-000000", "pollux-000001"}
    expired = next(item for item in items if item.request_id == "pollux-000000")
    success = next(item for item in items if item.request_id == "pollux-000001")

    assert expired.status == "expired"
    assert expired.error == "Request expired before execution"
    assert expired.provider_status == "batch_expired"

    assert success.status == "succeeded"
    assert success.response is not None
    assert success.response["text"] == '{"summary":"A"}'
    assert success.response["structured"] == {"summary": "A"}
    assert success.response["reasoning"] == "Reasoned"
    assert success.response["usage"]["total_tokens"] == 3
    assert success.finish_reason == "completed"


@pytest.mark.asyncio
async def test_openai_collect_deferred_leaves_plain_json_text_unstructured() -> None:
    """Deferred collection should only surface structured payloads for schema-backed jobs."""
    files = _FakeBatchFilesClient()
    files.contents["file_out"] = json.dumps(
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

    batches = _FakeBatchesClient()
    batches.retrieve_result = {"output_file_id": "file_out", "metadata": {}}
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    items = await provider.collect_deferred(ProviderDeferredHandle(job_id="batch_123"))

    assert items[0].response == {
        "text": '{"plain":true}',
        "usage": {"total_tokens": 1},
        "finish_reason": "completed",
    }


@pytest.mark.asyncio
async def test_openai_collect_deferred_cleans_up_owned_files() -> None:
    """Direct collection should cleanup provider-owned input files after success."""
    files = _FakeBatchFilesClient()
    files.contents["file_out"] = json.dumps(
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

    batches = _FakeBatchesClient()
    batches.retrieve_result = {
        "status": "completed",
        "output_file_id": "file_out",
        "metadata": {},
    }
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    await provider.collect_deferred(
        ProviderDeferredHandle(
            job_id="batch_123",
            provider_state={
                "owned_file_ids": ["file_batch_input", "file_uploaded_pdf"]
            },
        )
    )

    assert files.deleted_file_ids == ["file_batch_input", "file_uploaded_pdf"]


@pytest.mark.asyncio
async def test_openai_collect_deferred_synthesizes_batch_level_failure_items() -> None:
    """Batch-level terminal failures should expand into per-request diagnostics."""
    files = _FakeBatchFilesClient()

    batches = _FakeBatchesClient()
    batches.retrieve_result = {
        "status": "failed",
        "metadata": {"pollux_request_count": "2"},
        "errors": {
            "data": [
                {
                    "code": "model_not_found",
                    "message": "The provided model is not supported by the Batch API.",
                    "param": "body.model",
                }
            ]
        },
    }
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    items = await provider.collect_deferred(
        ProviderDeferredHandle(
            job_id="batch_123",
            provider_state={"request_ids": ["custom-a", "custom-b"]},
        )
    )

    assert items == [
        ProviderDeferredItem(
            request_id="custom-a",
            status="failed",
            error="The provided model is not supported by the Batch API.",
            provider_status="model_not_found",
        ),
        ProviderDeferredItem(
            request_id="custom-b",
            status="failed",
            error="The provided model is not supported by the Batch API.",
            provider_status="model_not_found",
        ),
    ]


@pytest.mark.asyncio
async def test_openai_collect_deferred_synthesizes_missing_cancelled_items() -> None:
    """Partial cancelled batches should fill in missing request ids."""
    files = _FakeBatchFilesClient()
    files.contents["file_out"] = json.dumps(
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

    batches = _FakeBatchesClient()
    batches.retrieve_result = {
        "status": "cancelled",
        "output_file_id": "file_out",
        "metadata": {"pollux_request_count": "2"},
    }
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    items = await provider.collect_deferred(
        ProviderDeferredHandle(
            job_id="batch_123",
            provider_state={"request_ids": ["pollux-000000", "pollux-000001"]},
        )
    )

    assert items == [
        ProviderDeferredItem(
            request_id="pollux-000000",
            status="succeeded",
            response={
                "text": "Answer 1",
                "usage": {"total_tokens": 1},
                "finish_reason": "completed",
            },
            provider_status="completed",
            finish_reason="completed",
        ),
        ProviderDeferredItem(
            request_id="pollux-000001",
            status="cancelled",
            error=None,
            provider_status="cancelled",
        ),
    ]


@pytest.mark.asyncio
async def test_openai_collect_deferred_reads_nested_http_error_body() -> None:
    """Batch HTTP failures should surface the nested OpenAI API error message."""
    files = _FakeBatchFilesClient()
    files.contents["file_out"] = json.dumps(
        {
            "custom_id": "pollux-000000",
            "response": {
                "status_code": 400,
                "body": {
                    "error": {
                        "code": "invalid_request_error",
                        "message": "schema invalid",
                    }
                },
            },
            "error": None,
        }
    )

    batches = _FakeBatchesClient()
    batches.retrieve_result = {"output_file_id": "file_out", "metadata": {}}
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    items = await provider.collect_deferred(ProviderDeferredHandle(job_id="batch_123"))

    assert items == [
        ProviderDeferredItem(
            request_id="pollux-000000",
            status="failed",
            error="schema invalid",
        )
    ]


@pytest.mark.asyncio
async def test_openai_collect_deferred_preserves_incomplete_provider_status() -> None:
    """Batch success items should report the actual Responses API body status."""
    files = _FakeBatchFilesClient()
    files.contents["file_out"] = json.dumps(
        {
            "custom_id": "pollux-000000",
            "response": {
                "status_code": 200,
                "body": {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "truncated",
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

    batches = _FakeBatchesClient()
    batches.retrieve_result = {"output_file_id": "file_out", "metadata": {}}
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    items = await provider.collect_deferred(ProviderDeferredHandle(job_id="batch_123"))

    assert items == [
        ProviderDeferredItem(
            request_id="pollux-000000",
            status="succeeded",
            response={
                "text": "truncated",
                "usage": {"total_tokens": 1},
                "finish_reason": "max_output_tokens",
            },
            provider_status="incomplete",
            finish_reason="max_output_tokens",
        )
    ]


@pytest.mark.asyncio
async def test_openai_cancel_deferred_calls_batches_cancel() -> None:
    """Deferred cancellation should delegate to the Batch API."""
    files = _FakeBatchFilesClient()
    batches = _FakeBatchesClient()
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    await provider.cancel_deferred(ProviderDeferredHandle(job_id="batch_123"))

    assert batches.cancelled_job_id == "batch_123"


@pytest.mark.asyncio
async def test_openai_cancel_deferred_cleans_up_when_batch_is_terminal() -> None:
    """Terminal cancel responses should cleanup owned input files."""
    files = _FakeBatchFilesClient()
    batches = _FakeBatchesClient()
    batches.cancel_result = type(
        "Batch", (), {"id": "batch_123", "status": "cancelled"}
    )()
    provider = OpenAIProvider("test-key")
    provider._client = type("Client", (), {"files": files, "batches": batches})()

    await provider.cancel_deferred(
        ProviderDeferredHandle(
            job_id="batch_123",
            provider_state={
                "owned_file_ids": ["file_batch_input", "file_uploaded_pdf"]
            },
        )
    )

    assert files.deleted_file_ids == ["file_batch_input", "file_uploaded_pdf"]


# =============================================================================
# Gemini Deferred Delivery (Characterization)
# =============================================================================


class _FakeGeminiFilesClient:
    """Captures Gemini Files API interactions for batch tests."""

    def __init__(self) -> None:
        self.upload_calls: list[dict[str, Any]] = []
        self.deleted_file_ids: list[str] = []
        self.download_contents: dict[str, bytes] = {}

    async def upload(self, **kwargs: Any) -> Any:
        self.upload_calls.append(kwargs)
        config = kwargs.get("config")
        mime_type = (
            config.get("mime_type")
            if isinstance(config, dict)
            else getattr(config, "mime_type", None)
        )
        if mime_type == "application/jsonl":
            return type(
                "File",
                (),
                {
                    "name": "files/batch_input",
                    "uri": "https://example.test/files/batch_input",
                    "state": "ACTIVE",
                },
            )()
        return type(
            "File",
            (),
            {
                "name": "files/uploaded_pdf",
                "uri": "https://example.test/files/uploaded_pdf",
                "state": "ACTIVE",
            },
        )()

    async def delete(self, *, name: str) -> None:
        self.deleted_file_ids.append(name)

    async def download(self, *, file: str) -> bytes:
        return self.download_contents[file]


class _FakeGeminiBatchesClient:
    """Captures Gemini Batch API interactions for characterization tests."""

    def __init__(self) -> None:
        self.create_kwargs: dict[str, Any] | None = None
        self.get_result: Any = None
        self.cancelled_name: str | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.create_kwargs = kwargs
        return type(
            "Batch",
            (),
            {
                "name": "batches/123",
                "create_time": datetime(2026, 3, 1, tzinfo=timezone.utc),
            },
        )()

    async def get(self, *, name: str) -> Any:
        _ = name
        return self.get_result

    async def cancel(self, *, name: str) -> None:
        self.cancelled_name = name


def _make_gemini_client(
    *,
    files: _FakeGeminiFilesClient,
    batches: _FakeGeminiBatchesClient,
) -> Any:
    return type(
        "Client",
        (),
        {
            "aio": type("Aio", (), {"files": files, "batches": batches})(),
        },
    )()


@pytest.mark.asyncio
async def test_gemini_submit_deferred_characterizes_inlined_batch_request(
    tmp_path: Path,
) -> None:
    """Deferred submission should reuse Gemini generate-content payloads."""
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    files = _FakeGeminiFilesClient()
    batches = _FakeGeminiBatchesClient()
    provider = GeminiProvider("test-key")
    provider._client = _make_gemini_client(files=files, batches=batches)

    snapshot, _, requirements, config = make_interaction(
        provider="gemini",
        model=GEMINI_MODEL,
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
        },
        content="prompt",
    )
    snapshot = replace(
        snapshot, sources=(Source.from_file(pdf_path, mime_type="application/pdf"),)
    )
    inputs = [
        Input(content="Summarize this"),
        Input(content="Answer the question"),
    ]

    handle = await provider.submit_deferred(
        snapshot,
        inputs,
        requirements,
        config,
        request_ids=["pollux-000000", "pollux-000001"],
    )

    assert handle.job_id == "batches/123"
    assert handle.provider_state == {
        "request_ids": ["pollux-000000", "pollux-000001"],
        "owned_file_ids": ["files/uploaded_pdf"],
        "has_response_schema": True,
    }

    assert len(files.upload_calls) == 1
    assert batches.create_kwargs is not None
    assert batches.create_kwargs["model"] == GEMINI_MODEL

    src = batches.create_kwargs["src"]
    assert len(src) == 2
    assert src[0].metadata == {"pollux_request_id": "pollux-000000"}
    assert src[0].config.response_mime_type == "application/json"
    assert src[1].metadata == {"pollux_request_id": "pollux-000001"}
    assert (
        src[1].contents[0].file_data.file_uri
        == "https://example.test/files/uploaded_pdf"
    )


@pytest.mark.asyncio
async def test_gemini_submit_deferred_preserves_video_settings(
    tmp_path: Path,
) -> None:
    """Deferred Gemini requests should preserve video settings through upload."""
    video_path = tmp_path / "lecture.mp4"
    video_path.write_bytes(b"fake-mp4")

    files = _FakeGeminiFilesClient()
    batches = _FakeGeminiBatchesClient()
    provider = GeminiProvider("test-key")
    provider._client = _make_gemini_client(files=files, batches=batches)

    snapshot, _, requirements, config = make_interaction(
        provider="gemini",
        model=GEMINI_MODEL,
        content="prompt",
    )
    video_source = Source.from_file(
        video_path, mime_type="video/mp4"
    ).with_gemini_video_settings(
        start_offset="40s",
        end_offset="80s",
        fps=1.0,
    )
    snapshot = replace(snapshot, sources=(video_source,))
    inputs = [Input(content="Describe this clip")]

    await provider.submit_deferred(
        snapshot,
        inputs,
        requirements,
        config,
        request_ids=["pollux-000000"],
    )

    assert batches.create_kwargs is not None
    src = batches.create_kwargs["src"]
    assert len(src) == 1
    # URI comes from the fake files client's fixed fixture value.
    assert (
        src[0].contents[0].file_data.file_uri
        == "https://example.test/files/uploaded_pdf"
    )
    assert src[0].contents[0].video_metadata.start_offset == "40s"
    assert src[0].contents[0].video_metadata.end_offset == "80s"
    assert src[0].contents[0].video_metadata.fps == 1.0


@pytest.mark.asyncio
async def test_gemini_submit_deferred_switches_to_file_input_when_inline_too_large(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Oversized Gemini deferred payloads should upload a JSONL batch file."""
    monkeypatch.setattr(gemini_module, "_GEMINI_BATCH_INLINE_LIMIT_BYTES", 1)

    files = _FakeGeminiFilesClient()
    batches = _FakeGeminiBatchesClient()
    provider = GeminiProvider("test-key")
    provider._client = _make_gemini_client(files=files, batches=batches)

    snapshot, _, requirements, config = make_interaction(
        provider="gemini",
        model=GEMINI_MODEL,
        content="prompt",
    )
    inputs = [
        Input(content="Summarize this"),
        Input(content="Answer the question"),
    ]

    handle = await provider.submit_deferred(
        snapshot,
        inputs,
        requirements,
        config,
        request_ids=["pollux-000000", "pollux-000001"],
    )

    assert handle.job_id == "batches/123"
    assert handle.provider_state == {
        "request_ids": ["pollux-000000", "pollux-000001"],
        "owned_file_ids": ["files/batch_input"],
        "has_response_schema": False,
    }

    assert len(files.upload_calls) == 1
    assert files.upload_calls[0]["config"] == {"mime_type": "application/jsonl"}
    assert batches.create_kwargs is not None
    assert batches.create_kwargs["model"] == GEMINI_MODEL
    assert batches.create_kwargs["src"].file_name == "files/batch_input"


@pytest.mark.asyncio
async def test_gemini_collect_deferred_parses_inlined_responses_and_cleans_up() -> None:
    """Gemini collection should use inlined batch responses and metadata ids."""
    files = _FakeGeminiFilesClient()
    batches = _FakeGeminiBatchesClient()
    batches.get_result = type(
        "Batch",
        (),
        {
            "state": "JOB_STATE_PARTIALLY_SUCCEEDED",
            "create_time": datetime(2026, 3, 1, tzinfo=timezone.utc),
            "end_time": datetime(2026, 3, 1, 0, 5, tzinfo=timezone.utc),
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
                                        "content": {"parts": [{"text": "Answer 2"}]},
                                    }
                                ],
                                "usage_metadata": {
                                    "prompt_token_count": 1,
                                    "candidates_token_count": 2,
                                    "total_token_count": 3,
                                },
                            },
                        },
                        {
                            "metadata": {"pollux_request_id": "pollux-000000"},
                            "error": {"code": 400, "message": "bad input"},
                        },
                    ]
                },
            )(),
        },
    )()
    provider = GeminiProvider("test-key")
    provider._client = _make_gemini_client(files=files, batches=batches)

    handle = ProviderDeferredHandle(
        job_id="batches/123",
        provider_state={
            "request_ids": ["pollux-000000", "pollux-000001"],
            "owned_file_ids": ["files/uploaded_pdf"],
        },
    )
    snapshot = await provider.inspect_deferred(handle)
    items = await provider.collect_deferred(handle)

    assert snapshot.status == "partial"
    assert snapshot.request_count == 2
    assert snapshot.succeeded == 1
    assert snapshot.failed == 1
    assert snapshot.pending == 0
    assert items == [
        ProviderDeferredItem(
            request_id="pollux-000001",
            status="succeeded",
            response={
                "text": "Answer 2",
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "total_tokens": 3,
                },
                "finish_reason": "stop",
            },
            provider_status="succeeded",
            finish_reason="stop",
        ),
        ProviderDeferredItem(
            request_id="pollux-000000",
            status="failed",
            error="bad input",
            provider_status="400",
        ),
    ]
    assert files.deleted_file_ids == ["files/uploaded_pdf", "files/uploaded_pdf"]


@pytest.mark.asyncio
async def test_gemini_collect_deferred_parses_file_output_and_cleans_up() -> None:
    """Gemini file-backed collection should recover request ids from metadata."""
    files = _FakeGeminiFilesClient()
    files.download_contents["files/output"] = (
        json.dumps(
            {
                "metadata": {"pollux_request_id": "pollux-000001"},
                "response": {
                    "candidates": [
                        {
                            "finish_reason": "STOP",
                            "content": {"parts": [{"text": "Answer 2"}]},
                        }
                    ],
                    "usage_metadata": {
                        "prompt_token_count": 1,
                        "candidates_token_count": 2,
                        "total_token_count": 3,
                    },
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "metadata": {"pollux_request_id": "pollux-000000"},
                "error": {"code": 400, "message": "bad input"},
            }
        )
    ).encode("utf-8")

    batches = _FakeGeminiBatchesClient()
    batches.get_result = type(
        "Batch",
        (),
        {
            "state": "JOB_STATE_PARTIALLY_SUCCEEDED",
            "create_time": datetime(2026, 3, 1, tzinfo=timezone.utc),
            "end_time": datetime(2026, 3, 1, 0, 5, tzinfo=timezone.utc),
            "error": None,
            "dest": type("Dest", (), {"file_name": "files/output"})(),
            "completion_stats": type(
                "CompletionStats",
                (),
                {
                    "successful_count": 1,
                    "failed_count": 1,
                    "incomplete_count": 0,
                },
            )(),
        },
    )()
    provider = GeminiProvider("test-key")
    provider._client = _make_gemini_client(files=files, batches=batches)

    handle = ProviderDeferredHandle(
        job_id="batches/123",
        provider_state={
            "request_ids": ["pollux-000000", "pollux-000001"],
            "owned_file_ids": ["files/batch_input"],
        },
    )
    snapshot = await provider.inspect_deferred(handle)
    items = await provider.collect_deferred(handle)

    assert snapshot.status == "partial"
    assert snapshot.request_count == 2
    assert snapshot.succeeded == 1
    assert snapshot.failed == 1
    assert snapshot.pending == 0
    assert items == [
        ProviderDeferredItem(
            request_id="pollux-000001",
            status="succeeded",
            response={
                "text": "Answer 2",
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "total_tokens": 3,
                },
                "finish_reason": "stop",
            },
            provider_status="succeeded",
            finish_reason="stop",
        ),
        ProviderDeferredItem(
            request_id="pollux-000000",
            status="failed",
            error="bad input",
            provider_status="400",
        ),
    ]
    assert files.deleted_file_ids == ["files/batch_input", "files/batch_input"]


# =============================================================================
# Anthropic Deferred Delivery (Characterization)
# =============================================================================


class _FakeAnthropicBatchFilesClient:
    """Captures Anthropic Files API interactions for batch tests."""

    def __init__(self) -> None:
        self.deleted_file_ids: list[str] = []
        self.upload_calls: list[dict[str, Any]] = []

    async def upload(self, **kwargs: Any) -> Any:
        self.upload_calls.append(kwargs)
        return type("FileMetadata", (), {"id": "file_uploaded_pdf"})()

    async def delete(self, file_id: str, **kwargs: Any) -> None:
        _ = kwargs
        self.deleted_file_ids.append(file_id)


class _AsyncAnthropicResults:
    """Simple async iterator wrapper for fake batch result rows."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self._index = 0

    def __aiter__(self) -> _AsyncAnthropicResults:
        self._index = 0
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._rows):
            raise StopAsyncIteration
        row = self._rows[self._index]
        self._index += 1
        return row


class _FakeAnthropicBatchesClient:
    """Captures Anthropic Message Batches API interactions."""

    def __init__(self) -> None:
        self.create_kwargs: dict[str, Any] | None = None
        self.retrieve_result: Any = None
        self.results_rows: list[Any] = []
        self.cancelled_batch_id: str | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.create_kwargs = kwargs
        return type(
            "MessageBatch",
            (),
            {
                "id": "msgbatch_123",
                "created_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
            },
        )()

    async def retrieve(self, message_batch_id: str) -> Any:
        _ = message_batch_id
        return self.retrieve_result

    def results(self, message_batch_id: str) -> Any:
        _ = message_batch_id
        return _AsyncAnthropicResults(self.results_rows)

    async def cancel(self, message_batch_id: str) -> Any:
        self.cancelled_batch_id = message_batch_id
        return self.retrieve_result


class _FakeAnthropicAwaitableResultsBatchesClient(_FakeAnthropicBatchesClient):
    """Variant whose results() method must be awaited before iteration."""

    async def results(self, message_batch_id: str) -> Any:
        _ = message_batch_id
        return _AsyncAnthropicResults(self.results_rows)


def _make_anthropic_client(
    *,
    files: _FakeAnthropicBatchFilesClient,
    batches: _FakeAnthropicBatchesClient,
) -> Any:
    return type(
        "Client",
        (),
        {
            "messages": type("Messages", (), {"batches": batches})(),
            "beta": type("Beta", (), {"files": files})(),
        },
    )()


@pytest.mark.asyncio
async def test_anthropic_submit_deferred_characterizes_message_batch_request(
    tmp_path: Path,
) -> None:
    """Deferred submission should build Anthropic message-batch requests."""
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    files = _FakeAnthropicBatchFilesClient()
    batches = _FakeAnthropicBatchesClient()
    provider = AnthropicProvider("test-key")
    provider._client = _make_anthropic_client(files=files, batches=batches)

    snapshot, _, requirements, config = make_interaction(
        provider="anthropic",
        model=ANTHROPIC_MODEL,
        response_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
        },
        content="prompt",
    )
    snapshot = replace(
        snapshot, sources=(Source.from_file(pdf_path, mime_type="application/pdf"),)
    )
    inputs = [
        Input(content="Summarize this"),
        Input(content="Answer the question"),
    ]

    handle = await provider.submit_deferred(
        snapshot,
        inputs,
        requirements,
        config,
        request_ids=["pollux-000000", "pollux-000001"],
    )

    assert handle.job_id == "msgbatch_123"
    assert handle.provider_state == {
        "request_ids": ["pollux-000000", "pollux-000001"],
        "owned_file_ids": ["file_uploaded_pdf"],
        "has_response_schema": True,
    }

    assert len(files.upload_calls) == 1
    assert batches.create_kwargs is not None
    assert batches.create_kwargs["extra_headers"] == {
        "anthropic-beta": "files-api-2025-04-14"
    }
    requests = list(batches.create_kwargs["requests"])
    assert [item["custom_id"] for item in requests] == [
        "pollux-000000",
        "pollux-000001",
    ]
    assert requests[0]["params"]["output_config"]["format"]["type"] == "json_schema"
    assert requests[1]["params"]["messages"][0]["content"][0]["source"]["file_id"] == (
        "file_uploaded_pdf"
    )


@pytest.mark.asyncio
async def test_anthropic_collect_deferred_parses_result_stream_and_cleans_up() -> None:
    """Anthropic collection should parse async JSONL results by custom_id."""
    files = _FakeAnthropicBatchFilesClient()
    batches = _FakeAnthropicBatchesClient()
    batches.retrieve_result = type(
        "MessageBatch",
        (),
        {
            "id": "msgbatch_123",
            "processing_status": "ended",
            "created_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
            "ended_at": datetime(2026, 3, 1, 0, 5, tzinfo=timezone.utc),
            "expires_at": datetime(2026, 3, 2, tzinfo=timezone.utc),
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
    batches.results_rows = [
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
                                        {"type": "text", "text": "Answer 2"},
                                    )()
                                ],
                                "usage": type(
                                    "Usage", (), {"input_tokens": 1, "output_tokens": 2}
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
    provider = AnthropicProvider("test-key")
    provider._client = _make_anthropic_client(files=files, batches=batches)

    handle = ProviderDeferredHandle(
        job_id="msgbatch_123",
        provider_state={
            "request_ids": ["pollux-000000", "pollux-000001"],
            "owned_file_ids": ["file_uploaded_pdf"],
        },
    )
    snapshot = await provider.inspect_deferred(handle)
    items = await provider.collect_deferred(handle)

    assert snapshot.status == "partial"
    assert snapshot.request_count == 2
    assert snapshot.succeeded == 1
    assert snapshot.failed == 1
    assert snapshot.pending == 0
    assert items == [
        ProviderDeferredItem(
            request_id="pollux-000001",
            status="succeeded",
            response={
                "text": "Answer 2",
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "total_tokens": 3,
                },
                "response_id": "msg_123",
                "finish_reason": "stop",
            },
            provider_status="succeeded",
            finish_reason="stop",
        ),
        ProviderDeferredItem(
            request_id="pollux-000000",
            status="cancelled",
            provider_status="canceled",
        ),
    ]
    assert files.deleted_file_ids == ["file_uploaded_pdf", "file_uploaded_pdf"]


@pytest.mark.asyncio
async def test_anthropic_collect_deferred_awaits_results_coroutine() -> None:
    """Anthropic collection should handle SDK results() methods that are awaitable."""
    files = _FakeAnthropicBatchFilesClient()
    batches = _FakeAnthropicAwaitableResultsBatchesClient()
    batches.retrieve_result = type(
        "MessageBatch",
        (),
        {
            "id": "msgbatch_123",
            "processing_status": "ended",
            "created_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
            "ended_at": datetime(2026, 3, 1, 0, 5, tzinfo=timezone.utc),
            "expires_at": datetime(2026, 3, 2, tzinfo=timezone.utc),
            "results_url": "https://example.test/results.jsonl",
            "request_counts": type(
                "Counts",
                (),
                {
                    "processing": 0,
                    "succeeded": 1,
                    "errored": 0,
                    "canceled": 0,
                    "expired": 0,
                },
            )(),
        },
    )()
    batches.results_rows = [
        type(
            "Row",
            (),
            {
                "custom_id": "pollux-000000",
                "result": type(
                    "Succeeded",
                    (),
                    {
                        "type": "succeeded",
                        "message": type(
                            "Message",
                            (),
                            {
                                "id": "msg_awaitable",
                                "content": [
                                    type(
                                        "Block",
                                        (),
                                        {"type": "text", "text": "Answer 1"},
                                    )()
                                ],
                                "usage": type(
                                    "Usage", (), {"input_tokens": 2, "output_tokens": 3}
                                )(),
                                "stop_reason": "end_turn",
                            },
                        )(),
                    },
                )(),
            },
        )(),
    ]
    provider = AnthropicProvider("test-key")
    provider._client = _make_anthropic_client(files=files, batches=batches)

    handle = ProviderDeferredHandle(
        job_id="msgbatch_123",
        provider_state={
            "request_ids": ["pollux-000000"],
            "owned_file_ids": ["file_uploaded_pdf"],
        },
    )
    items = await provider.collect_deferred(handle)

    assert items == [
        ProviderDeferredItem(
            request_id="pollux-000000",
            status="succeeded",
            response={
                "text": "Answer 1",
                "usage": {
                    "input_tokens": 2,
                    "output_tokens": 3,
                    "total_tokens": 5,
                },
                "response_id": "msg_awaitable",
                "finish_reason": "stop",
            },
            provider_status="succeeded",
            finish_reason="stop",
        )
    ]
