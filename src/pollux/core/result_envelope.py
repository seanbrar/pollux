"""User-facing result structures returned by the pipeline."""

from __future__ import annotations

import math
import typing
from typing import Literal, TypeGuard


class ResultEnvelope(typing.TypedDict, total=False):
    """Stable result shape for all extractions.

    This type ensures consistent structure regardless of extraction method.
    The 'total=False' allows optional fields while maintaining type safety.

    This is the main result structure that users receive from the pipeline.
    """

    # Core fields (always present)
    status: Literal["ok", "partial", "error"]  # End-to-end status
    answers: list[str]  # Always present, padded if needed
    extraction_method: str  # Which transform/fallback succeeded
    confidence: float  # 0.0-1.0 extraction confidence

    # Optional fields
    structured_data: typing.Any  # Original structured data if available
    metrics: dict[str, typing.Any]  # Telemetry metrics
    usage: dict[str, typing.Any]  # Token usage data
    diagnostics: dict[str, typing.Any]  # When diagnostics enabled
    validation_warnings: tuple[str, ...]  # Schema/contract violations


def _validate_result_envelope_reason(obj: object) -> str | None:
    """Internal: return None when valid, else a concise reason string.

    Centralizes structural rules so both the boolean guard and dev-time
    validators share a single source of truth.
    """
    if not isinstance(obj, dict):
        return f"ResultEnvelope must be dict, got {type(obj).__name__}"
    status = obj.get("status")
    if status not in ("ok", "partial", "error"):
        return "'status' must be one of {'ok','partial','error'}"
    answers = obj.get("answers")
    if not isinstance(answers, list):
        if isinstance(answers, str):
            return "'answers' must be list[str], got str; wrap in a list"
        return f"'answers' must be list[str], got {type(answers).__name__}"
    if not all(isinstance(a, str) for a in answers):
        bad = next((type(a).__name__ for a in answers if not isinstance(a, str)), "?")
        return f"'answers' elements must be str; found {bad}"
    method = obj.get("extraction_method")
    if not (isinstance(method, str) and method.strip() != ""):
        return "'extraction_method' must be a non-empty str"
    if "confidence" not in obj:
        return "'confidence' must be present"
    conf = obj.get("confidence")
    if not isinstance(conf, int | float):
        return "'confidence' must be int|float"
    try:
        cf = float(conf)
    except Exception:
        return "'confidence' must be convertible to float"
    if math.isnan(cf) or not (0.0 <= cf <= 1.0):
        return "'confidence' must be in [0.0, 1.0]"
    if "metrics" in obj and not isinstance(obj.get("metrics"), dict):
        return "'metrics' must be dict when present"
    if "usage" in obj and not isinstance(obj.get("usage"), dict):
        return "'usage' must be dict when present"
    return None


def is_result_envelope(obj: object) -> TypeGuard[ResultEnvelope]:
    """Return True if ``obj`` structurally looks like a ``ResultEnvelope``.

    Public TypeGuard for convenient type-narrowing in calling code and tests.
    This is a lightweight structural check, not a full validator. Runtime
    shape guarantees come primarily from the executor's final invariant and the
    `ResultBuilder`. For detailed diagnostics (a human-friendly reason string),
    use ``explain_invalid_result_envelope``.

    Notes:
    - This helper focuses on clarity and fast guards; it may evolve along with
      the envelope's structural contract.
    - Dev-time validation can be enabled via ``POLLUX_PIPELINE_VALIDATE=1`` and
      related helpers in ``pipeline._devtools``.
    """
    return _validate_result_envelope_reason(obj) is None


def explain_invalid_result_envelope(obj: object) -> str | None:
    """Return a concise reason when a `ResultEnvelope` shape is invalid.

    Public counterpart to the internal validator; returns None when the
    object structurally satisfies the `ResultEnvelope` contract, otherwise
    a short, actionable reason string for diagnostics and dev tooling.
    """
    return _validate_result_envelope_reason(obj)
