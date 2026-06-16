"""Real API integration tests.

These tests make real provider API calls and are intentionally compact:
- ENABLE_API_TESTS=1 is required to run any API tests
- GEMINI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / OPENROUTER_API_KEY
  are required per provider fixture

The suite prioritizes high-signal end-to-end coverage with a small call budget.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import io
import json
import time
from typing import TYPE_CHECKING, Any, cast

import pytest

import pollux
from pollux import (
    Environment,
    Input,
    Message,
    Source,
    ToolCall,
    ToolDeclaration,
    ToolResult,
)
from pollux.config import Config
from pollux.providers import gemini as gemini_module

if TYPE_CHECKING:
    from pollux.config import ProviderName

pytestmark = [
    pytest.mark.api,
    pytest.mark.slow,
]

_PROVIDERS: list[tuple[str, str, str]] = [
    ("gemini", "gemini_api_key", "gemini_test_model"),
    ("openai", "openai_api_key", "openai_test_model"),
    ("anthropic", "anthropic_api_key", "anthropic_test_model"),
    ("openrouter", "openrouter_api_key", "openrouter_test_model"),
]
_GEMINI_REASONING_MODEL = "gemini-3-flash-preview"


def _api_kwargs(
    provider: str, *, max_tokens: int = 32, **kwargs: Any
) -> dict[str, Any]:
    """Return low-output live-test generation arguments where the provider supports them."""
    if provider in {"openai", "openrouter"}:
        kwargs.setdefault("max_tokens", max(max_tokens, 512))
    elif provider != "gemini":
        kwargs.setdefault("max_tokens", max_tokens)
    return kwargs


def _minimal_pdf_bytes() -> bytes:
    """Return a minimal valid single-page PDF."""
    header = b"%PDF-1.4\n"
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n"
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
            b"/Contents 4 0 R >>\n"
            b"endobj\n"
        ),
        b"4 0 obj\n<< /Length 0 >>\nstream\n\nendstream\nendobj\n",
    ]

    body = header
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(body))
        body += obj

    xref_pos = len(body)
    xref = b"xref\n0 5\n0000000000 65535 f \n" + b"".join(
        f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets
    )
    trailer = (
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode("ascii")
        + b"\n%%EOF\n"
    )
    return body + xref + trailer


def _pdf_escape(text: str) -> str:
    """Escape a string for use in a PDF text stream."""
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_with_text(text: str) -> bytes:
    """Return a tiny single-page PDF with visible text."""
    stream = (f"BT\n/F1 12 Tf\n72 120 Td\n({_pdf_escape(text)}) Tj\nET\n").encode(
        "ascii"
    )
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n"
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 200] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\n"
            b"endobj\n"
        ),
        (
            b"4 0 obj\n<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"endstream\nendobj\n"
        ),
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]

    body = b"%PDF-1.4\n"
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(body))
        body += obj

    xref_pos = len(body)
    xref = b"xref\n0 6\n0000000000 65535 f \n" + b"".join(
        f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets
    )
    trailer = (
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode("ascii")
        + b"\n%%EOF\n"
    )
    return body + xref + trailer


def _provider_config(
    request: pytest.FixtureRequest,
    *,
    provider: str,
    api_key_fixture: str,
    model_fixture: str,
) -> Config:
    api_key = request.getfixturevalue(api_key_fixture)
    model = request.getfixturevalue(model_fixture)
    return Config(provider=cast("ProviderName", provider), model=model, api_key=api_key)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "api_key_fixture", "model_fixture"),
    _PROVIDERS,
    ids=["gemini", "openai", "anthropic", "openrouter"],
)
async def test_live_source_patterns_and_generation_controls(
    request: pytest.FixtureRequest,
    provider: str,
    api_key_fixture: str,
    model_fixture: str,
) -> None:
    """E2E: run_many + Source.from_json stay coherent and in-order."""
    config = _provider_config(
        request,
        provider=provider,
        api_key_fixture=api_key_fixture,
        model_fixture=model_fixture,
    )
    source = Source.from_json({"planet": "Neptune", "code": "ZX-41"})

    # gpt-5-nano currently rejects temperature/top_p; keep controls provider-aware.
    kwargs = _api_kwargs(
        provider,
        max_tokens=1024 if provider == "openai" else 32,
        instructions="One line.",
        temperature=0.2 if provider == "gemini" else None,
        top_p=0.9 if provider == "gemini" else None,
    )

    result = await pollux.run_many(
        prompts=(
            "JSON planet. Reply exactly FIRST:<planet>.",
            "JSON code. Reply exactly SECOND:<code>.",
        ),
        sources=(source,),
        config=config,
        **kwargs,
    )

    assert len(result.outputs) == 2
    assert sum(o.metrics.n_calls for o in result.outputs) == 2
    assert "first" in result.answers[0].lower()
    assert "neptune" in result.answers[0].lower()
    assert "second" in result.answers[1].lower()
    assert "zx-41" in result.answers[1].lower()
    assert result.usage.total_tokens > 0

    # instructions="One line." should constrain output shape.
    for answer in result.answers:
        assert len(answer.strip().splitlines()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "api_key_fixture", "model_fixture"),
    _PROVIDERS,
    ids=["gemini", "openai", "anthropic", "openrouter"],
)
async def test_live_tool_calls_conversation_and_reasoning_roundtrip(
    request: pytest.FixtureRequest,
    provider: str,
    api_key_fixture: str,
    model_fixture: str,
) -> None:
    """E2E: tool call + continuation preserves ordering and context."""
    config = _provider_config(
        request,
        provider=provider,
        api_key_fixture=api_key_fixture,
        model_fixture=model_fixture,
    )
    tools = [
        {
            "name": "get_secret",
            "description": "Return a code.",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        },
    ]

    env = Environment(tools=[ToolDeclaration.from_dict(t) for t in tools])

    first = await pollux.interact(
        env,
        Input("Call get_secret once with topic='orbit'."),
        config=config,
        **_api_kwargs(
            provider,
            max_tokens=64,
            tool_choice="required",
        ),
    )

    assert first.tool_calls
    call = first.tool_calls[0]
    assert call.name == "get_secret"

    tool_ref = call.id if call.id else "get_secret"

    tool_results = [
        ToolResult(
            call_id=tool_ref,
            content=json.dumps({"code": "K9-ORBIT"}),
        )
    ]

    response_schema: dict[str, Any] | None = {
        "type": "object",
        "properties": {"secret_code": {"type": "string"}},
        "required": ["secret_code"],
    }

    second = await pollux.interact(
        Environment(),
        Input(
            continuation=first.continuation,
            tool_results=tool_results,
        ),
        config=config,
        output=response_schema,
        **_api_kwargs(
            provider,
            max_tokens=96,
            reasoning_effort="low" if provider == "openai" else None,
        ),
    )

    assert second.structured
    assert second.structured.get("secret_code") == "K9-ORBIT"

    assert second.continuation is not None
    messages = second.continuation.messages
    assert messages
    tool_indexes = [
        i
        for i, msg in enumerate(messages)
        if msg.role == "tool" and msg.tool_call_id == tool_ref
    ]
    assert tool_indexes
    assert tool_indexes[0] < len(messages) - 1

    if provider == "openai" and second.reasoning:
        assert isinstance(second.reasoning, str)
        assert second.reasoning.strip()


@pytest.mark.asyncio
async def test_live_anthropic_parallel_tool_result_history_roundtrip(
    anthropic_api_key: str,
    anthropic_test_model: str,
) -> None:
    """E2E: Anthropic accepts history with parallel tool results + prompt."""
    config = Config(
        provider="anthropic",
        model=anthropic_test_model,
        api_key=anthropic_api_key,
    )
    tools = [
        {
            "name": "get_secret",
            "description": "Return a code for a given topic.",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        },
    ]
    history = [
        Message(role="user", content="Need orbit and launch codes."),
        Message(
            role="assistant",
            content="",
            tool_calls=(
                ToolCall.from_text(
                    id="call_orbit", name="get_secret", arguments_text="{}"
                ),
                ToolCall.from_text(
                    id="call_launch", name="get_secret", arguments_text="{}"
                ),
            ),
        ),
        Message(
            role="tool",
            tool_call_id="call_orbit",
            content=json.dumps({"code": "K9-ORBIT"}),
        ),
        Message(
            role="tool",
            tool_call_id="call_launch",
            content=json.dumps({"code": "L2-LAUNCH"}),
        ),
    ]

    env = Environment(tools=[ToolDeclaration.from_dict(t) for t in tools])

    result = await pollux.interact(
        env,
        Input(
            content="Reply with both codes in one line.",
            history=history,
        ),
        config=config,
        **_api_kwargs(
            "anthropic",
            max_tokens=32,
            tool_choice="none",
        ),
    )

    assert result.text
    answer = result.text.lower()
    assert "k9-orbit" in answer
    assert "l2-launch" in answer


@pytest.mark.asyncio
async def test_gemini_reasoning_roundtrip_on_gemini3(gemini_api_key: str) -> None:
    """E2E: Gemini reasoning_effort works on Gemini 3 model family."""
    config = Config(
        provider="gemini",
        model=_GEMINI_REASONING_MODEL,
        api_key=gemini_api_key,
    )

    result = await pollux.run(
        "Reply exactly OK.",
        config=config,
        reasoning_effort="low",
    )

    assert "ok" in result.text.lower()
    assert result.reasoning
    assert isinstance(result.reasoning, str)
    assert result.reasoning.strip()


@pytest.mark.asyncio
async def test_gemini_url_context_roundtrip(
    gemini_api_key: str,
    gemini_test_model: str,
) -> None:
    """E2E: Gemini URL Context retrieves a public URL and exposes metadata."""
    config = Config(
        provider="gemini",
        model=gemini_test_model,
        api_key=gemini_api_key,
    )

    result = await pollux.run(
        (
            "Read the URL. Reply exactly GEMINI_URL_CONTEXT_OK if the README title "
            "mentions OpenAI Python API library."
        ),
        source=Source.from_uri(
            "https://raw.githubusercontent.com/openai/openai-python/main/README.md",
            mime_type="text/markdown",
        ).with_gemini_url_context(),
        config=config,
    )

    assert "gemini_url_context_ok" in result.text.lower()
    assert result.diagnostics.raw is not None
    raw = result.diagnostics.raw["response"]
    # url_context_metadata is model-dependent and might not be populated by all models/versions.
    artifacts = raw.get("artifacts")
    if artifacts and "url_context_metadata" in artifacts:
        assert artifacts["url_context_metadata"]


@pytest.mark.asyncio
async def test_gemini_live_deferred_inline_submit_and_inspect(
    gemini_api_key: str,
    gemini_test_model: str,
) -> None:
    """E2E: Gemini inline deferred submission returns a live inspectable handle."""
    config = Config(
        provider="gemini",
        model=gemini_test_model,
        api_key=gemini_api_key,
    )
    job: pollux.DeferredHandle | None = None
    try:
        job = await pollux.defer(
            "Reply exactly LIVE_DEFERRED_INLINE_OK.",
            config=config,
        )
        snapshot = await pollux.inspect_deferred(job)

        assert snapshot.job_id == job.job_id
        assert snapshot.request_count == 1
        assert snapshot.succeeded + snapshot.failed + snapshot.pending == 1
        assert snapshot.provider_status

        if snapshot.is_terminal:
            result = await pollux.collect_deferred(job)
            assert result.outputs[0].diagnostics.raw is not None
            assert result.outputs[0].diagnostics.raw["deferred"]["job_id"] == job.job_id
    finally:
        if job is not None:
            with suppress(Exception):
                await pollux.cancel_deferred(job)


@pytest.mark.asyncio
async def test_gemini_live_deferred_file_submit_and_inspect(
    monkeypatch: pytest.MonkeyPatch,
    gemini_api_key: str,
    gemini_test_model: str,
) -> None:
    """E2E: Gemini file-backed deferred submission supports bounded cancellation."""
    monkeypatch.setattr(gemini_module, "_GEMINI_BATCH_INLINE_LIMIT_BYTES", 1)

    config = Config(
        provider="gemini",
        model=gemini_test_model,
        api_key=gemini_api_key,
    )
    job: pollux.DeferredHandle | None = None
    cancelled = False
    try:
        job = await pollux.defer(
            (
                "Reply exactly LIVE_DEFERRED_FILE_ONE.",
                "Reply exactly LIVE_DEFERRED_FILE_TWO.",
            ),
            config=config,
        )
        await pollux.cancel_deferred(job)
        cancelled = True
        snapshot = await pollux.inspect_deferred(job)

        assert snapshot.job_id == job.job_id
        assert snapshot.request_count == 2
        assert snapshot.succeeded + snapshot.failed + snapshot.pending == 2
        assert snapshot.provider_status
        assert job.provider_state is not None
        assert job.provider_state["owned_file_ids"]
    finally:
        if job is not None and not cancelled:
            with suppress(Exception):
                await pollux.cancel_deferred(job)


@pytest.mark.asyncio
async def test_anthropic_live_deferred_submit_inspect_and_cancel(
    anthropic_api_key: str,
    anthropic_test_model: str,
) -> None:
    """E2E: Anthropic deferred submission supports bounded cancellation."""
    config = Config(
        provider="anthropic",
        model=anthropic_test_model,
        api_key=anthropic_api_key,
    )
    job: pollux.DeferredHandle | None = None
    cancelled = False
    try:
        job = await pollux.defer(
            "Reply exactly LIVE_ANTHROPIC_DEFERRED_CANCEL_OK.",
            config=config,
            max_tokens=16,
        )
        await pollux.cancel_deferred(job)
        cancelled = True
        snapshot = await pollux.inspect_deferred(job)

        assert snapshot.job_id == job.job_id
        assert snapshot.request_count == 1
        assert snapshot.succeeded + snapshot.failed + snapshot.pending == 1
        assert snapshot.provider_status
    finally:
        if job is not None and not cancelled:
            with suppress(Exception):
                await pollux.cancel_deferred(job)


@pytest.mark.asyncio
async def test_openrouter_reasoning_roundtrip(
    openrouter_api_key: str,
    openrouter_test_model: str,
) -> None:
    """E2E: OpenRouter reasoning_effort works on the stable reasoning route."""
    config = Config(
        provider="openrouter",
        model=openrouter_test_model,
        api_key=openrouter_api_key,
    )

    result = await pollux.run(
        "Reply exactly OK.",
        config=config,
        reasoning_effort="low",
        max_tokens=256,
    )

    assert "ok" in result.text.lower()
    assert result.diagnostics.raw is not None
    raw = result.diagnostics.raw["response"]
    provider_state = raw.get("provider_state")
    assert isinstance(provider_state, dict)
    assert provider_state.get("openrouter_reasoning_details")


@pytest.mark.asyncio
async def test_openai_binary_upload_cleanup_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
    openai_api_key: str,
    openai_test_model: str,
    tmp_path: Any,
) -> None:
    """E2E: OpenAI binary upload call succeeds and cleanup hook is invoked."""
    from pollux.providers.openai import OpenAIProvider

    deleted_file_ids: list[str] = []
    original_delete_file = OpenAIProvider.delete_file

    async def _delete_file_spy(self: OpenAIProvider, file_id: str) -> None:
        deleted_file_ids.append(file_id)
        await original_delete_file(self, file_id)

    monkeypatch.setattr(OpenAIProvider, "delete_file", _delete_file_spy)

    pdf_path = tmp_path / "tiny.pdf"
    pdf_path.write_bytes(_minimal_pdf_bytes())

    config = Config(provider="openai", model=openai_test_model, api_key=openai_api_key)
    result = await pollux.run(
        "Reply exactly PDF_OK.",
        source=Source.from_file(pdf_path, mime_type="application/pdf"),
        config=config,
        max_tokens=512,
    )

    assert "pdf_ok" in result.text.lower()
    assert deleted_file_ids
    assert all(isinstance(file_id, str) and file_id for file_id in deleted_file_ids)

    remote = await pollux.run(
        "Read the remote file and reply exactly REMOTE_MARKDOWN_OK.",
        source=Source.from_uri(
            "https://raw.githubusercontent.com/openai/openai-python/main/README.md",
            mime_type="text/markdown",
        ),
        config=config,
        max_tokens=512,
    )
    assert "remote_markdown_ok" in remote.text.lower()


@pytest.mark.asyncio
async def test_openai_live_batch_validation_failure_shape_characterization(
    openai_api_key: str,
) -> None:
    """E2E: Batch validation failures surface on the batch object, not per-row output files."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=openai_api_key)
    batch_id: str | None = None
    final_status: str | None = None
    file_ids_to_delete: set[str] = set()

    try:
        lines = [
            {
                "custom_id": "pollux-live-invalid-model",
                "method": "POST",
                "url": "/v1/responses",
                "body": {
                    "model": "not-a-real-openai-model",
                    "input": "Reply OK.",
                },
            },
        ]

        payload = (
            "\n".join(json.dumps(line, separators=(",", ":")) for line in lines) + "\n"
        ).encode("utf-8")
        upload = io.BytesIO(payload)
        upload.name = "pollux-live-batch.jsonl"

        batch_file = await client.files.create(file=upload, purpose="batch")
        file_ids_to_delete.add(batch_file.id)

        batch = await client.batches.create(
            input_file_id=batch_file.id,
            endpoint="/v1/responses",
            completion_window="24h",
        )
        batch_id = batch.id

        deadline = time.monotonic() + 180
        while True:
            batch = await client.batches.retrieve(batch.id)
            if batch.status in {"completed", "failed", "cancelled", "expired"}:
                break
            if time.monotonic() >= deadline:
                pytest.fail(f"Timed out waiting for OpenAI batch {batch.id} to finish")
            await asyncio.sleep(5)

        final_status = batch.status
        assert batch.status == "failed"
        assert batch.output_file_id is None
        assert batch.error_file_id is None
        assert batch.errors is not None
        assert batch.errors.data
        assert batch.errors.data[0].code == "model_not_found"
        assert batch.errors.data[0].param == "body.model"
        message = batch.errors.data[0].message
        assert message is not None
        assert "not supported by the Batch API" in message
    finally:
        if batch_id is not None and final_status not in {
            "failed",
            "cancelled",
            "expired",
            "completed",
        }:
            with suppress(Exception):
                await client.batches.cancel(batch_id)
        for file_id in file_ids_to_delete:
            with suppress(Exception):
                await client.files.delete(file_id)
        await client.close()


@pytest.mark.asyncio
async def test_openai_live_response_incomplete_shape_characterization(
    openai_api_key: str,
    openai_test_model: str,
) -> None:
    """E2E: A live Responses API call exposes `status=incomplete` with reason details."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=openai_api_key)

    try:
        response = await client.responses.create(
            model=openai_test_model,
            input="Count from one to twenty in words.",
            max_output_tokens=16,
        )

        assert response.status == "incomplete"
        assert response.incomplete_details is not None
        assert response.incomplete_details.reason == "max_output_tokens"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_openrouter_local_pdf_roundtrip(
    openrouter_api_key: str,
    openrouter_test_model: str,
    tmp_path: Any,
) -> None:
    """E2E: OpenRouter local PDF uploads remain accepted on the stable route."""
    pdf_path = tmp_path / "token.pdf"
    token = "PDFLOCAL314159"
    pdf_path.write_bytes(_pdf_with_text(token))

    config = Config(
        provider="openrouter",
        model=openrouter_test_model,
        api_key=openrouter_api_key,
    )
    result = await pollux.run(
        "Reply exactly with the PDF token.",
        source=Source.from_file(pdf_path, mime_type="application/pdf"),
        config=config,
        max_tokens=512,
    )

    assert result.text.strip() == token
    if result.usage:
        assert result.usage.total_tokens > 0
