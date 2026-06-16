"""``Output``: the completed result of one model interaction.

``Output`` is an immutable object with named facets. It is not a dict-shaped
envelope: code reads ``output.text`` / ``output.tool_calls`` and serializes with
``to_jsonable()``. There is no ``confidence``, ``extraction_method``, or
single-result ``status`` heuristic — completion legibility lives in
``metrics.completion_status``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pollux.interaction.continuation import Continuation
    from pollux.interaction.tools import ToolCall

#: Whether a turn stopped cleanly, was truncated by a token limit, was cut off by
#: another provider-side condition, or failed.
CompletionStatus = Literal["clean", "truncated", "cutoff", "error"]

_TRUNCATED_FINISH = {"max_tokens", "length"}
_CUTOFF_FINISH = {
    "content_filter",
    "safety",
    "recitation",
    "prohibited_content",
    "blocklist",
    "spii",
}


def completion_status(
    finish_reason: str | None,
    *,
    error_category: str | None = None,
) -> CompletionStatus:
    """Map a normalized finish reason and error category to a completion status.

    ``error_category`` values come from
    :func:`pollux.providers._errors._detect_error_category`. A context-overflow
    error is reported as ``"truncated"``; any other categorized error is
    ``"error"``. Otherwise a recognized truncation or cutoff finish reason maps
    accordingly, and anything else (including an unrecognized reason) is clean.
    """
    if error_category == "context_overflow":
        return "truncated"
    if error_category is not None:
        return "error"
    if finish_reason is None:
        return "clean"
    reason = finish_reason.lower()
    if reason in _TRUNCATED_FINISH:
        return "truncated"
    if reason in _CUTOFF_FINISH:
        return "cutoff"
    return "clean"


@dataclass(frozen=True, slots=True)
class Usage:
    """Normalized token and cache usage where providers report it."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None

    @classmethod
    def from_dict(cls, usage: Mapping[str, int]) -> Usage:
        """Build from the provider's flat usage dict, ignoring unknown keys."""
        reasoning = usage.get("reasoning_tokens")
        cached = usage.get("cached_tokens")
        return cls(
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            reasoning_tokens=int(reasoning) if reasoning is not None else None,
            cached_tokens=int(cached) if cached is not None else None,
        )

    def to_jsonable(self) -> dict[str, int]:
        """Serialize to a compact dict (optional facets omitted when unset)."""
        payload = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }
        if self.reasoning_tokens is not None:
            payload["reasoning_tokens"] = self.reasoning_tokens
        if self.cached_tokens is not None:
            payload["cached_tokens"] = self.cached_tokens
        return payload


@dataclass(frozen=True, slots=True)
class Metrics:
    """Pollux execution metrics for one interaction."""

    duration_s: float = 0.0
    n_calls: int = 1
    cache_used: bool = False
    cache_mode: str = "none"
    cache_hit: bool = False
    finish_reason: str | None = None
    completion_status: CompletionStatus = "clean"

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "duration_s": self.duration_s,
            "n_calls": self.n_calls,
            "cache_used": self.cache_used,
            "cache_mode": self.cache_mode,
            "cache_hit": self.cache_hit,
            "finish_reason": self.finish_reason,
            "completion_status": self.completion_status,
        }


@dataclass(frozen=True, slots=True)
class Diagnostics:
    """Provider and Pollux details for debugging; not normal control flow."""

    raw: dict[str, Any] | None = None

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict (empty when no detail is set)."""
        return dict(self.raw) if self.raw else {}


def _jsonable_structured(value: Any) -> Any:
    """Return a JSON-compatible structured payload where Pollux can guarantee it."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


@dataclass(frozen=True, slots=True)
class Output:
    """The completed result of one model interaction, as named facets."""

    text: str = ""
    structured: Any = None
    reasoning: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    continuation: Continuation | None = None
    usage: Usage = field(default_factory=Usage)
    metrics: Metrics = field(default_factory=Metrics)
    diagnostics: Diagnostics = field(default_factory=Diagnostics)

    def to_jsonable(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict (optional facets omitted)."""
        payload: dict[str, Any] = {"text": self.text}
        if self.structured is not None:
            payload["structured"] = _jsonable_structured(self.structured)
        if self.reasoning is not None:
            payload["reasoning"] = self.reasoning
        if self.tool_calls:
            payload["tool_calls"] = [tc.to_jsonable() for tc in self.tool_calls]
        if self.continuation is not None:
            payload["continuation"] = self.continuation.to_jsonable()
        payload["usage"] = self.usage.to_jsonable()
        payload["metrics"] = self.metrics.to_jsonable()
        diagnostics = self.diagnostics.to_jsonable()
        if diagnostics:
            payload["diagnostics"] = diagnostics
        return payload
