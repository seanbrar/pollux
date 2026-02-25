"""Real API integration tests.

These tests make real Gemini/OpenAI calls and are intentionally compact:
- ENABLE_API_TESTS=1 is required to run any API tests
- GEMINI_API_KEY / OPENAI_API_KEY are required per provider fixture

The suite prioritizes high-signal end-to-end coverage with a small call budget.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import pytest

import pollux
from pollux.config import Config
from pollux.options import Options
from pollux.source import Source

if TYPE_CHECKING:
    from pollux.config import ProviderName

pytestmark = [pytest.mark.api, pytest.mark.slow]

_PROVIDERS: list[tuple[str, str, str]] = [
    ("gemini", "gemini_api_key", "gemini_test_model"),
    ("openai", "openai_api_key", "openai_test_model"),
]
_GEMINI_REASONING_MODEL = "gemini-3-flash-preview"


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
    ids=["gemini", "openai"],
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
    source = Source.from_json(
        {"planet": "Neptune", "code": "ZX-41"},
        identifier="api-json-source",
    )

    # gpt-5-nano currently rejects temperature/top_p; keep controls provider-aware.
    options = Options(
        system_instruction="Return one line only. No extra words.",
        temperature=0.2 if provider == "gemini" else None,
        top_p=0.9 if provider == "gemini" else None,
    )

    result = await pollux.run_many(
        prompts=(
            "From the JSON source, reply with exactly: FIRST:<planet>",
            "From the JSON source, reply with exactly: SECOND:<code>",
        ),
        sources=(source,),
        config=config,
        options=options,
    )

    assert len(result["answers"]) == 2
    assert result["metrics"]["n_calls"] == 2
    assert "first" in result["answers"][0].lower()
    assert "neptune" in result["answers"][0].lower()
    assert "second" in result["answers"][1].lower()
    assert "zx-41" in result["answers"][1].lower()
    assert isinstance(result["usage"].get("total_tokens"), int)
    assert result["usage"]["total_tokens"] > 0

    # system_instruction="Return one line only." should constrain output shape.
    for answer in result["answers"]:
        assert len(answer.strip().splitlines()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "api_key_fixture", "model_fixture"),
    _PROVIDERS,
    ids=["gemini", "openai"],
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
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
    }
    if provider == "openai":
        parameters["additionalProperties"] = False
    tools = [
        {
            "name": "get_secret",
            "description": "Return a code for a given topic.",
            "parameters": parameters,
        },
    ]

    first = await pollux.run(
        (
            "Call get_secret exactly once with topic='orbit'. "
            "Once you receive the tool result, return it in the structured response."
        ),
        config=config,
        options=Options(tools=tools, tool_choice="required", history=[]),
    )

    tool_calls_raw = first.get("tool_calls")
    calls = (
        tool_calls_raw[0] if isinstance(tool_calls_raw, list) and tool_calls_raw else []
    )
    assert calls
    call = calls[0]
    assert isinstance(call, dict)
    assert call.get("name") == "get_secret"

    call_id_raw = call.get("id")
    tool_ref = (
        call_id_raw if isinstance(call_id_raw, str) and call_id_raw else "get_secret"
    )

    tool_results = [
        {
            "role": "tool",
            "tool_call_id": tool_ref,
            "content": json.dumps({"code": "K9-ORBIT"}),
        }
    ]

    response_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"secret_code": {"type": "string"}},
        "required": ["secret_code"],
    }
    if provider == "openai":
        response_schema["additionalProperties"] = False

    second = await pollux.continue_tool(
        continue_from=first,
        tool_results=tool_results,
        config=config,
        options=Options(
            reasoning_effort="medium" if provider == "openai" else None,
            response_schema=response_schema,
        ),
    )

    assert "structured" in second
    assert second["structured"][0].get("secret_code") == "K9-ORBIT"

    second_state = second.get("_conversation_state")
    assert isinstance(second_state, dict)
    second_history = second_state.get("history")
    assert isinstance(second_history, list)
    tool_indexes = [
        i
        for i, item in enumerate(second_history)
        if isinstance(item, dict)
        and item.get("role") == "tool"
        and item.get("tool_call_id") == tool_ref
    ]
    assert tool_indexes
    assert tool_indexes[0] < len(second_history) - 1

    if provider == "openai" and "reasoning" in second:
        assert isinstance(second["reasoning"], list)
        assert len(second["reasoning"]) == 1
        assert isinstance(second["reasoning"][0], str)
        assert second["reasoning"][0].strip()


@pytest.mark.asyncio
async def test_gemini_reasoning_roundtrip_on_gemini3(gemini_api_key: str) -> None:
    """E2E: Gemini reasoning_effort works on Gemini 3 model family."""
    config = Config(
        provider="gemini",
        model=_GEMINI_REASONING_MODEL,
        api_key=gemini_api_key,
    )

    result = await pollux.run(
        "Reply with exactly OK.",
        config=config,
        options=Options(reasoning_effort="medium"),
    )

    assert result["status"] == "ok"
    assert "ok" in result["answers"][0].lower()
    assert "reasoning" in result
    assert isinstance(result["reasoning"], list)
    assert len(result["reasoning"]) == 1
    assert isinstance(result["reasoning"][0], str)
    assert result["reasoning"][0].strip()


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
        "Reply with exactly PDF_OK.",
        source=Source.from_file(pdf_path, mime_type="application/pdf"),
        config=config,
    )

    assert result["status"] == "ok"
    assert "pdf_ok" in result["answers"][0].lower()
    assert deleted_file_ids
    assert all(isinstance(file_id, str) and file_id for file_id in deleted_file_ids)
