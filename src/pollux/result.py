"""Phase 4: Result extraction and envelope building."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from pydantic import BaseModel

if TYPE_CHECKING:
    from pollux.execute import ExecutionTrace
    from pollux.plan import Plan


class ResultEnvelope(TypedDict, total=False):
    """Standard result envelope returned by Pollux."""

    status: Literal["ok", "partial", "error"]
    answers: list[str]  # Stable core contract.
    structured: list[Any]
    reasoning: list[str | None]
    confidence: float
    extraction_method: str
    usage: dict[str, int]
    metrics: dict[str, Any]
    diagnostics: dict[str, Any]
    _conversation_state: dict[str, Any]


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

    # Determine status based on answer quality
    status: Literal["ok", "partial", "error"] = "ok"
    empty_count = sum(1 for a in answers if not a.strip())
    if empty_count == len(answers) and answers:
        status = "error"
    elif empty_count > 0:
        status = "partial"

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
        },
    )
    if wants_structured:
        envelope["structured"] = structured_values
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
