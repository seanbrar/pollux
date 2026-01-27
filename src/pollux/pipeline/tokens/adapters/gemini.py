"""Gemini-specific token estimation with bias compensation.

Pure, testable, and minimal. No SDK calls, no content reads. The algorithm is
base_tokens x bias_factor with a simple confidence-based range.
"""

from __future__ import annotations

from dataclasses import dataclass

from pollux.core.types import Source, TokenEstimate

# Provider knowledge (not configuration)
HEURISTICS: dict[str, float] = {
    # source_type -> tokens per byte (<= 1.0) or fixed tokens (> 1.0)
    # Tuned using token_accuracy_analysis.md to reduce systematic overestimation.
    "text": 1 / 4.2,  # ~4.2 chars per token (kept)
    "image": 1 / 750,  # was 1/500
    "video": 1 / 2500,  # was 1/2000
    "file": 1 / 1200,  # was 1/1000 (generic file/PDFs)
    "youtube": 225,  # fixed estimate
    "arxiv": 7500,  # fixed estimate
}

MIN_TOKEN_FLOOR = 10
MIXED_CONTENT_PENALTY = 0.9  # Empirical: mixed content less predictable

CONFIDENCE: dict[str, float] = {
    "text": 0.9,
    "image": 0.5,
    "video": 0.7,
    "file": 0.7,
    "youtube": 0.8,
    "arxiv": 0.8,
}


@dataclass(frozen=True)
class GeminiBiases:
    """Empirically-derived compensation factors (versioned)."""

    image: float = 5.0
    video: float = 0.85
    text: float = 1.0
    file: float = 1.0

    @classmethod
    def v1_august_2025(cls) -> GeminiBiases:  # pragma: no cover - alias
        """Aug 2025 legacy-aligned defaults."""
        return cls()

    @classmethod
    def latest(cls) -> GeminiBiases:  # pragma: no cover - alias
        """Alias to the current tagged biases version."""
        return cls.v1_august_2025()


class GeminiEstimationAdapter:
    """Pure token estimation with bias compensation.

    Algorithm: expected_tokens = base_tokens x bias_factor.
    Range: linear band derived from confidence.
    """

    def __init__(self, biases: GeminiBiases | None = None) -> None:
        """Initialize the adapter with versioned biases."""
        self.biases = biases or GeminiBiases.latest()

    @property
    def provider(self) -> str:  # pragma: no cover - trivial
        """Provider identifier."""
        return "gemini"

    # --- Public API ---
    def estimate(self, source: Source) -> TokenEstimate:
        """The algorithm: base_tokens x bias_factor with simple bands."""
        effective_type = self._effective_type(source)

        base = self._base_tokens(source, effective_type)
        bias = getattr(self.biases, effective_type, 1.0)
        expected = max(MIN_TOKEN_FLOOR, int(base * bias))

        confidence = self._confidence_for(effective_type)
        range_factor = 0.1 if confidence > 0.8 else 0.2 if confidence > 0.6 else 0.3

        min_tokens = max(MIN_TOKEN_FLOOR, int(expected * (1 - range_factor)))
        max_tokens = int(expected * (1 + range_factor))

        return TokenEstimate(min_tokens, expected, max_tokens, confidence)

    def aggregate(self, estimates: list[TokenEstimate]) -> TokenEstimate:
        """Sum bounds; reduce confidence for mixed content; add breakdown."""
        if not estimates:
            return TokenEstimate(0, 0, 0, 1.0)
        if len(estimates) == 1:
            return estimates[0]

        total_min = sum(e.min_tokens for e in estimates)
        total_exp = sum(e.expected_tokens for e in estimates)
        total_max = sum(e.max_tokens for e in estimates)
        confidence = min(e.confidence for e in estimates) * MIXED_CONTENT_PENALTY
        breakdown = {f"source_{i}": e for i, e in enumerate(estimates)}
        return TokenEstimate(total_min, total_exp, total_max, confidence, breakdown)

    # --- Internals ---
    def _base_tokens(self, source: Source, effective_type: str) -> float:
        """Compute base tokens from metadata using HEURISTICS."""
        value = HEURISTICS.get(effective_type, HEURISTICS["file"])
        if value <= 1.0:
            return max(source.size_bytes, 1) * value
        return float(value)

    def _effective_type(self, source: Source) -> str:
        """Refine 'file' by MIME to 'image'/'video' where possible."""
        st = source.source_type
        if st in {"text", "youtube", "arxiv"}:
            return st
        mime = (source.mime_type or "").lower()
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("video/"):
            return "video"
        return "file"

    def _confidence_for(self, effective_type: str) -> float:
        """Return confidence for an effective type (0-1)."""
        return CONFIDENCE.get(effective_type, 0.8)
