"""Unit tests for debug raw preview helpers and flags."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from pollux._dev_flags import dev_raw_preview_enabled
from pollux.pipeline._debug_preview import build_raw_preview

pytestmark = pytest.mark.unit


def test_dev_flags_raw_preview_enabled_env_and_override(monkeypatch: Any) -> None:
    # Override takes precedence
    monkeypatch.delenv("POLLUX_TELEMETRY_RAW_PREVIEW", raising=False)
    assert dev_raw_preview_enabled(override=True) is True
    assert dev_raw_preview_enabled(override=False) is False

    # Env exact-match semantics
    monkeypatch.setenv("POLLUX_TELEMETRY_RAW_PREVIEW", "1")
    assert dev_raw_preview_enabled() is True
    monkeypatch.setenv("POLLUX_TELEMETRY_RAW_PREVIEW", "0")
    assert dev_raw_preview_enabled() is False
    monkeypatch.setenv("POLLUX_TELEMETRY_RAW_PREVIEW", "true")
    assert dev_raw_preview_enabled() is False


def test_build_raw_preview_basic_fields_and_truncation() -> None:
    raw = {
        "model": "m",
        "text": "x" * 20,
        "usage": {"total_token_count": 3},
    }
    prev = build_raw_preview(raw, limit=10)
    assert prev.get("model") == "m"
    assert isinstance(prev.get("usage"), dict)
    t = prev.get("text")
    assert isinstance(t, str) and t.endswith("[TRUNCATED]")


def test_build_raw_preview_candidates_from_dict_shape() -> None:
    raw = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "candidate text value"},
                    ]
                }
            }
        ]
    }
    prev = build_raw_preview(raw)
    assert prev.get("candidate0_text") == "candidate text value"


@dataclass
class _Part:
    text: str


@dataclass
class _Content:
    parts: list[_Part]


@dataclass
class _Candidate:
    content: _Content


@dataclass
class _ProviderRaw:
    candidates: list[_Candidate]


def test_build_raw_preview_candidates_from_provider_object() -> None:
    provider = _ProviderRaw(
        candidates=[_Candidate(content=_Content(parts=[_Part(text="abc")]))]
    )
    raw = {"provider_raw": provider, "model": "m"}
    prev = build_raw_preview(raw)
    assert prev.get("candidate0_text") == "abc"


def test_build_raw_preview_str_and_unknown() -> None:
    s_prev = build_raw_preview("hello world", limit=5)
    assert s_prev.get("text") == "hello... [TRUNCATED]"

    class _X:
        def __repr__(self) -> str:  # pragma: no cover - trivial
            return "X(1)"

    u_prev = build_raw_preview(_X())
    assert isinstance(u_prev.get("repr"), str)


def test_build_raw_preview_sanitizes_usage() -> None:
    raw = {
        "usage": {
            "total_token_count": 123,
            "nested": {"a": 1},
            "listy": [1, 2, 3],
            "note": "x" * 100,
        }
    }
    prev = build_raw_preview(raw, limit=16)
    usage = prev.get("usage")
    assert isinstance(usage, dict)
    # Keeps known numeric key
    assert usage.get("total_token_count") == 123
    # Drops nested/list values
    assert "nested" not in usage and "listy" not in usage
    # Truncates strings
    note_val = usage.get("note")
    assert isinstance(note_val, str) and note_val.endswith("[TRUNCATED]")


def test_build_raw_preview_finish_reason_from_dict_and_object() -> None:
    raw_dict = {"candidates": [{"finishReason": "STOP"}]}
    prev_d = build_raw_preview(raw_dict)
    assert prev_d.get("finish_reason") == "STOP"

    @dataclass
    class _CandFR:
        finish_reason: str

    @dataclass
    class _ProvFR:
        candidates: list[_CandFR]

    raw_obj = {"provider_raw": _ProvFR(candidates=[_CandFR(finish_reason="LENGTH")])}
    prev_o = build_raw_preview(raw_obj)
    assert prev_o.get("finish_reason") == "LENGTH"
