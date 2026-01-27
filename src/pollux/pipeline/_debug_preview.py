"""Small, safe helpers to build compact raw previews for debugging.

These helpers are intentionally independent of provider SDK types. They use
permissive duck-typing and defensive guards to extract a few useful fields
from raw provider responses without raising.
"""

from __future__ import annotations

from typing import Any, TypedDict

__all__ = ["RawPreview", "build_raw_preview"]


class RawPreview(TypedDict, total=False):
    """Typed structure for compact raw previews (all fields optional).

    The structure is intentionally minimal and provider-agnostic. Fields are
    sanitized and truncated to remain small and safe for telemetry/debugging.
    """

    model: str
    text: str
    candidate0_text: str
    usage: dict[str, int | float | str]
    finish_reason: str
    safety: str
    repr: str


def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[:limit] + "... [TRUNCATED]"


def _first_candidate_text_from_obj(obj: Any) -> str | None:
    """Best-effort extraction of first candidate text from SDK-like objects.

    Handles attribute-based access (e.g., ``obj.candidates[0].content.parts[0].text``)
    and returns None when traversal is not possible.
    """
    try:
        cands = getattr(obj, "candidates", None)
        if not cands:
            return None
        c0 = cands[0]
        content = getattr(c0, "content", None)
        parts = getattr(content, "parts", None)
        if not parts:
            return None
        p0 = parts[0]
        text = getattr(p0, "text", None)
        return text if isinstance(text, str) else None
    except Exception:
        return None


def _first_candidate_text_from_dict(dct: dict[str, Any]) -> str | None:
    """Best-effort extraction of first candidate text from dict-like shapes."""
    try:
        cands = dct.get("candidates")
        if not isinstance(cands, list | tuple) or not cands:
            return None
        c0 = cands[0]
        if not isinstance(c0, dict):
            return None
        content = c0.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list | tuple) or not parts:
            return None
        p0 = parts[0]
        if isinstance(p0, dict):
            text = p0.get("text")
            return text if isinstance(text, str) else None
        return None
    except Exception:
        return None


def _extract_finish_reason_from_obj(obj: Any) -> str | None:
    """Best-effort extraction of a finish reason from SDK-like objects."""
    try:
        cands = getattr(obj, "candidates", None)
        if not cands:
            return None
        c0 = cands[0]
        fr = getattr(c0, "finish_reason", None)
        return fr if isinstance(fr, str) and fr else None
    except Exception:
        return None


def _extract_finish_reason_from_dict(dct: dict[str, Any]) -> str | None:
    """Best-effort extraction of a finish reason from dict-like shapes."""
    fr = dct.get("finish_reason") or dct.get("finishReason")
    if isinstance(fr, str) and fr:
        return fr
    try:
        cands = dct.get("candidates")
        if isinstance(cands, list | tuple) and cands:
            c0 = cands[0]
            if isinstance(c0, dict):
                fr2 = c0.get("finish_reason") or c0.get("finishReason")
                if isinstance(fr2, str) and fr2:
                    return fr2
    except Exception:
        return None
    return None


def _sanitize_usage(
    usage: dict[str, Any], *, limit: int
) -> dict[str, int | float | str]:
    """Return a compact usage dict with only simple scalar fields.

    - Keeps a small allowlist of well-known keys when present (numeric or str).
    - Otherwise, includes only top-level numeric or short string values.
    - Drops nested structures entirely.
    - Truncates strings using the same limit as text.
    """
    # Deterministic priority order for common usage keys
    allowlist = (
        "total_token_count",
        "input_token_count",
        "output_token_count",
        "cache_read_tokens",
        "cache_write_tokens",
    )
    out: dict[str, int | float | str] = {}
    # First, include allowlisted keys in the defined priority order
    for k in (ak for ak in allowlist if ak in usage):
        v = usage.get(k)
        if isinstance(v, int | float):
            out[k] = v
        elif isinstance(v, str):
            out[k] = _truncate(v, limit)
        if len(out) >= 8:
            return out
    # Then, include other simple scalar keys up to the cap
    for k, v in usage.items():
        if k in out:
            continue
        if isinstance(v, int | float):
            out[k] = v
        elif isinstance(v, str):
            out[k] = _truncate(v, limit)
        if len(out) >= 8:
            break
    return out


def build_raw_preview(raw: Any, *, limit: int = 512) -> RawPreview:
    """Return a compact, truncated preview dict for raw provider output.

    The preview is designed for debug/telemetry usage and aims to be tiny,
    sanitized, and stable across provider shapes. It never raises.
    """
    preview: RawPreview = {}
    try:
        if isinstance(raw, str):
            preview["text"] = _truncate(raw, limit)
            return preview

        if isinstance(raw, dict):
            # Common fields
            model = raw.get("model")
            if isinstance(model, str):
                preview["model"] = model
            usage = raw.get("usage")
            if isinstance(usage, dict):
                preview["usage"] = _sanitize_usage(usage, limit=limit)
            text = raw.get("text")
            if isinstance(text, str):
                preview["text"] = _truncate(text, limit)
            # Try dict-based candidates
            cand_text = _first_candidate_text_from_dict(raw)
            if cand_text:
                preview["candidate0_text"] = _truncate(cand_text, limit)
            # Finish reason if present
            fr = _extract_finish_reason_from_dict(raw)
            if fr:
                preview["finish_reason"] = fr
            # If provider SDK objects are nested under a key (e.g., provider_raw), try attributes
            provider_raw = raw.get("provider_raw")
            if provider_raw is not None and "candidate0_text" not in preview:
                cand_text2 = _first_candidate_text_from_obj(provider_raw)
                if cand_text2:
                    preview["candidate0_text"] = _truncate(cand_text2, limit)
            # Extract finish reason from provider object when available
            if provider_raw is not None and "finish_reason" not in preview:
                fr2 = _extract_finish_reason_from_obj(provider_raw)
                if fr2:
                    preview["finish_reason"] = fr2
            return preview

        # Fallback: unknown shape; truncated repr
        preview["repr"] = _truncate(repr(raw), limit)
        return preview
    except Exception:
        # Never raise; fallback to truncated repr of the root object
        try:
            return {"repr": _truncate(repr(raw), limit)}
        except Exception:
            return {"repr": "<unrepresentable>"}
