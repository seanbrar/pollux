"""Dependency analyzer (preflight) for prompt/question sets.

Best-effort detector for follow-up questions that reference earlier prompts.
The heuristic combines:
- Regex cues: "as above", "as mentioned above", "following", "previous",
  explicit references like "Q2", "question 2", and ordinal references
  (e.g., "second question").
- Lightweight lexical overlap: content-word overlap against earlier prompts
  (Jaccard over stem-like tokens, stopwords removed).

Contract:
- Pure and deterministic (no IO, side effects, or provider coupling).
- Stable shape for outputs and unit-tested.
- Marked as "best-effort" only; callers should not rely on it for strict
  execution ordering without additional checks.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Final, Literal, TypedDict

if TYPE_CHECKING:  # import for typing only to satisfy linter rule
    from collections.abc import Iterable

__version__: Final[str] = "1.1.0"

# Thresholds and weights (tunable but constant by default)
OVERLAP_THRESHOLD: Final[float] = 0.30
PRONOUN_OVERLAP_THRESHOLD: Final[float] = 0.12
REGEX_BASE: Final[float] = 0.6
OVERLAP_BASE: Final[float] = 0.4
OVERLAP_WEIGHT: Final[float] = 0.4

# Rich type aliases for reason coding
ReasonPrefix = Literal[
    "regex",
    "ordinal",
    "overlap",
    "pronoun_overlap",
    "default_prev",
]

RegexReasonCode = Literal[
    "see_above",
    "following",
    "previous",
    "q_number",
    "question_number",
    "latter_former",
]

OrdinalWord = Literal["first", "second", "third", "fourth", "fifth"]


def make_regex_reason(code: RegexReasonCode) -> str:
    """Build a normalized regex-based reason string."""
    return f"regex:{code}"


def make_ordinal_reason(word: OrdinalWord) -> str:
    """Build a normalized ordinal-based reason string."""
    return f"ordinal:{word}"


def make_overlap_reason(value: float) -> str:
    """Build a normalized overlap-based reason string with 2-decimal precision."""
    return f"overlap:{value:.2f}"


def make_pronoun_overlap_reason(value: float) -> str:
    """Build a normalized pronoun-overlap reason string with 2-decimal precision."""
    return f"pronoun_overlap:{value:.2f}"


def make_default_prev_reason() -> str:
    """Build a normalized default-previous reason string for generic references."""
    return "default_prev:see_above"


# Semantic cue regexes: (compiled_regex, reason_code, has_numeric_group)
_CUE_REGEXES: Final[list[tuple[re.Pattern[str], RegexReasonCode, bool]]] = [
    (re.compile(r"\bas (?:mentioned\s+)?above\b", re.IGNORECASE), "see_above", False),
    (re.compile(r"\bfollowing\b", re.IGNORECASE), "following", False),
    (re.compile(r"\bprevious(?:\s+question)?\b", re.IGNORECASE), "previous", False),
    (re.compile(r"\bsee\s+(?:above|prior)\b", re.IGNORECASE), "see_above", False),
    (re.compile(r"\bq\s*(\d+)\b", re.IGNORECASE), "q_number", True),
    (re.compile(r"\bquestion\s*(\d+)\b", re.IGNORECASE), "question_number", True),
    (re.compile(r"\b(latter|former)\b", re.IGNORECASE), "latter_former", False),
]

_ORDINAL_TO_INDEX: dict[OrdinalWord, int] = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
}

_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "at",
        "by",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "as",
        "about",
        "into",
        "than",
    }
)

PRONOUN_REGEX: Final[re.Pattern[str]] = re.compile(
    r"\b(this|that|these|those)\b", re.IGNORECASE
)


def _tokenize(text: str) -> list[str]:
    w = re.findall(r"[A-Za-z0-9]+", text.lower())
    # lightweight stemming: strip common plural 's'
    out: list[str] = []
    for t in w:
        if t in _STOPWORDS:
            continue
        if len(t) > 3 and t.endswith("s"):
            t = t[:-1]
        out.append(t)
    return out


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return float(inter) / float(union or 1)


@dataclass(frozen=True)
class DependencyHint:
    """Best-effort dependency signal from one prompt to a prior prompt.

    Attributes:
        src_index: 1-based index of the referencing prompt.
        dst_index: 1-based index of the referenced earlier prompt.
        reasons: Human-readable list of cues that fired.
        score: Aggregate score (0..1) combining regex and overlap.
    """

    src_index: int
    dst_index: int
    reasons: tuple[str, ...]
    score: float


class DependencyHintDict(TypedDict):
    """Serialized hint for API/JSON output."""

    src_index: int
    dst_index: int
    reasons: list[str]
    score: float


class DependencyAnalysis(TypedDict):
    """Structured result of dependency analysis."""

    version: str
    note: str
    dependent_indices: list[int]
    hints: list[DependencyHintDict]


def analyze_dependencies(
    prompts: list[str],
    *,
    overlap_threshold: float | None = None,
    pronoun_overlap_threshold: float | None = None,
    regex_base: float | None = None,
    overlap_base: float | None = None,
    overlap_weight: float | None = None,
    default_prev_on_generic_reference: bool = True,
    max_lookback: int | None = None,
) -> DependencyAnalysis:
    """Analyze a list of prompts/questions and return dependency hints.

    This is a preflight helper intended to guide batching/grouping decisions.
    It never mutates input and always returns a stable, serializable shape.

    Args:
        prompts: List of user prompts (1-based indexing in results).
        overlap_threshold: Optional override for the Jaccard overlap threshold
            used to infer dependencies from content overlap. Default is
            `OVERLAP_THRESHOLD`.
        pronoun_overlap_threshold: Optional override for the lower Jaccard
            threshold when pronoun cues are present. Default is
            `PRONOUN_OVERLAP_THRESHOLD`.
        regex_base: Optional override for the base score when any regex cue is
            present. Default is `REGEX_BASE`.
        overlap_base: Optional override for the base score when only overlap
            cues are present. Default is `OVERLAP_BASE`.
        overlap_weight: Optional override for the weight applied to the overlap
            value in the score computation. Default is `OVERLAP_WEIGHT`.
        default_prev_on_generic_reference: When True, generic "see above" cues
            (without numeric/ordinal references) default to the immediately
            previous prompt when no overlap-based destination is selected.
            This improves recall for common phrasing. Default is True.
        max_lookback: If provided, restricts overlap comparison to only the last
            N prior prompts (e.g., 1 compares only to the immediately previous
            prompt). Default is None (search all prior prompts).

    Returns:
        Mapping with keys:
        - "dependent_indices": list[int] of prompts that likely depend on earlier ones
        - "hints": list[DependencyHint] as dicts
        - "version": semantic version string for the heuristic
        - "note": best-effort disclaimer
    """
    # Resolve effective thresholds/weights
    ov_threshold = OVERLAP_THRESHOLD if overlap_threshold is None else overlap_threshold
    pro_threshold = (
        PRONOUN_OVERLAP_THRESHOLD
        if pronoun_overlap_threshold is None
        else pronoun_overlap_threshold
    )
    base_regex = REGEX_BASE if regex_base is None else regex_base
    base_overlap = OVERLAP_BASE if overlap_base is None else overlap_base
    w_overlap = OVERLAP_WEIGHT if overlap_weight is None else overlap_weight

    tokens = [_tokenize(p or "") for p in prompts]
    hints: list[DependencyHint] = []
    dependent_indices: set[int] = set()

    for i, p in enumerate(prompts, start=1):
        if i == 1:
            continue
        reasons: list[str] = []
        dst: int | None = None
        has_generic_see_above = False

        # Regex cues and explicit references with semantic reason codes
        for rx, code, has_num in _CUE_REGEXES:
            m = rx.search(p)
            if not m:
                continue
            reasons.append(make_regex_reason(code))
            if code == "see_above" and not has_num:
                has_generic_see_above = True
            # explicit numeric reference (e.g., Q2, question 3)
            if has_num and m.lastindex:
                num_str = m.group(m.lastindex) or ""
                if num_str.isdigit():
                    num = int(num_str)
                    if 1 <= num < i:
                        dst = num

        # Ordinal form (handled explicitly here to avoid duplication)
        for word, idx in _ORDINAL_TO_INDEX.items():
            if re.search(rf"\b{word}\s+question\b", p, re.IGNORECASE) and idx < i:
                reasons.append(make_ordinal_reason(word))
                dst = idx
                break

        # Fallback: overlap with nearest predecessors
        best_overlap = 0.0
        best_j = None
        j_start = 1
        if max_lookback is not None and max_lookback > 0:
            j_start = max(1, i - max_lookback)
        for j in range(j_start, i):
            ov = _jaccard(tokens[i - 1], tokens[j - 1])
            if ov > best_overlap:
                best_overlap = ov
                best_j = j
        if (
            best_overlap >= ov_threshold and best_j is not None
        ):  # conservative threshold
            reasons.append(make_overlap_reason(best_overlap))
            if dst is None:
                dst = best_j

        # Pronoun + keyword overlap cue (best-effort): lower threshold
        if (
            dst is None
            and best_j is not None
            and PRONOUN_REGEX.search(p)
            and best_overlap >= pro_threshold
        ):
            reasons.append(make_pronoun_overlap_reason(best_overlap))
            dst = best_j

        # If we still don't have a destination, but there's a generic
        # "see above" cue, conservatively default to the immediately
        # previous prompt (if requested).
        if (
            dst is None
            and has_generic_see_above
            and default_prev_on_generic_reference
            and i > 1
        ):
            dst = i - 1
            reasons.append(make_default_prev_reason())

        if dst is not None:
            # Score: base REGEX_BASE if regex or ordinal cue is present, else OVERLAP_BASE;
            # then add OVERLAP_WEIGHT * overlap (capped at 1.0).
            base = (
                base_regex
                if any(r.startswith(("regex:", "ordinal:")) for r in reasons)
                else base_overlap
            )
            score = min(base + w_overlap * best_overlap, 1.0)
            hints.append(
                DependencyHint(
                    src_index=i, dst_index=dst, reasons=tuple(reasons), score=score
                )
            )
            dependent_indices.add(i)

    # Deterministic order aids testing and diffs
    hints_sorted = sorted(hints, key=lambda h: (h.src_index, -h.score, h.dst_index))

    return {
        "version": __version__,
        "note": "best-effort heuristic; use as guidance only",
        "dependent_indices": sorted(dependent_indices),
        "hints": [
            {
                "src_index": h.src_index,
                "dst_index": h.dst_index,
                "reasons": list(h.reasons),
                "score": h.score,
            }
            for h in hints_sorted
        ],
    }
