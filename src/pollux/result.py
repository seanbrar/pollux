"""Phase 4: Result extraction and envelope building."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from pydantic import BaseModel

if TYPE_CHECKING:
    from pollux.execute import ExecutionTrace
    from pollux.plan import Plan


class ResultEnvelope(TypedDict, total=False):
    """Standard result envelope returned by Pollux.

    ``status`` is ``"ok"`` when all answers are non-empty, ``"partial"`` when
    some are empty, or ``"error"`` when all are empty.
    """

    status: Literal["ok", "partial", "error"]
    answers: list[str]  # Stable core contract.
    #: Present only when ``response_schema`` was set in Options.
    structured: list[Any]
    reasoning: list[str | None]
    #: Heuristic: ``0.9`` for ``"ok"`` status, ``0.5`` otherwise.
    confidence: float
    #: Always ``"text"`` in v1.0.
    extraction_method: str
    #: Keys: ``input_tokens``, ``output_tokens``, ``total_tokens``,
    #: and optionally ``reasoning_tokens``.
    usage: dict[str, int]
    #: Keys: ``duration_s``, ``n_calls``, ``cache_used``, ``finish_reasons``.
    metrics: dict[str, Any]
    diagnostics: dict[str, Any]
    _conversation_state: dict[str, Any]
    tool_calls: list[list[dict[str, Any]]]


def build_result(plan: Plan, trace: ExecutionTrace) -> ResultEnvelope:
    """Build ResultEnvelope from execution trace.

    Extracts answers from responses with simple, predictable logic.
    """
    answers: list[str] = []
    structured_values: list[Any] = []
    schema_model = plan.request.options.response_schema_model()
    wants_structured = plan.request.options.response_schema is not None

    for response in trace.responses:
        text = _extract_text(response)
        answers.append(text)
        if wants_structured:
            raw_structured = _extract_structured(response, text=text)
            if (
                raw_structured is not None
                and isinstance(schema_model, type)
                and issubclass(schema_model, BaseModel)
            ):
                try:
                    structured_values.append(
                        schema_model.model_validate(raw_structured)
                    )
                except Exception:
                    structured_values.append(None)
            else:
                structured_values.append(raw_structured)

    reasoning_texts: list[str | None] = []
    has_reasoning = False
    for response in trace.responses:
        if "reasoning" in response:
            reasoning_texts.append(response["reasoning"])
            has_reasoning = True
        else:
            reasoning_texts.append(None)

    # Determine status based on answer quality
    status: Literal["ok", "partial", "error"] = "ok"
    empty_count = sum(1 for a in answers if not a.strip())
    if empty_count == len(answers) and answers:
        status = "error"
    elif empty_count > 0:
        status = "partial"

    # Extract finish reasons forwarded from providers.
    finish_reasons: list[str | None] = [
        response.get("finish_reason") for response in trace.responses
    ]

    envelope = ResultEnvelope(
        status=status,
        answers=answers,
        confidence=0.9 if status == "ok" else 0.5,
        extraction_method="text",
        usage=trace.usage,
        metrics={
            "duration_s": trace.duration_s,
            "n_calls": plan.n_calls,
            "cache_used": trace.cache_name is not None,
            "finish_reasons": finish_reasons,
        },
        diagnostics={
            "raw_responses": trace.responses,
        },
    )
    if wants_structured:
        envelope["structured"] = structured_values
    if has_reasoning:
        envelope["reasoning"] = reasoning_texts
    if trace.conversation_state is not None:
        envelope["_conversation_state"] = trace.conversation_state

    all_tool_calls: list[list[dict[str, Any]]] = []
    has_tools = False
    for response in trace.responses:
        tcs = response.get("tool_calls", [])
        all_tool_calls.append(tcs)
        if tcs:
            has_tools = True
    if has_tools:
        envelope["tool_calls"] = all_tool_calls

    return envelope


def _extract_text(response: dict[str, Any]) -> str:
    """Extract text from API response."""
    if "text" in response and isinstance(response["text"], str):
        return response["text"]

    try:
        candidates = response.get("candidates", [])
        if candidates:
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if parts:
                return str(parts[0].get("text", ""))
    except (KeyError, IndexError, TypeError):
        pass

    return ""


def _extract_structured(response: dict[str, Any], *, text: str) -> Any:
    """Extract structured payload from a provider response."""
    if "structured" in response:
        return response["structured"]
    if text:
        try:
            return json.loads(text)
        except Exception:
            return None
    return None
