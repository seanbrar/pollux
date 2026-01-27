"""Chunking utilities for long text and transcripts.

Goal: provide slim, ergonomic functions that examples can use to keep scripts
clean while leveraging library token estimation heuristics. These helpers are
provider-neutral at the API level and default to the Gemini estimation adapter
to approximate token counts.

APIs:
- chunk_text_by_tokens: split long text into token-bounded chunks with overlap
- chunk_transcript_by_tokens: split a list of (start,end,text) into chunks

Notes:
- Token counts are approximate and based on the same heuristics used by the
  planner's estimation adapter. Chunks aim to be <= target_tokens but may be
  slightly over or under due to boundary choices.
- Overlap is applied in tokens and approximated over word boundaries for text;
  for transcripts, the last segments are re-included to achieve approximate
  overlap.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import re

from pollux.core.sources import Source
from pollux.pipeline.tokens.adapters.gemini import GeminiEstimationAdapter

# --- Types ---


TokenEstimator = Callable[[str], int]


@dataclass(frozen=True)
class TranscriptSegment:  # noqa: D101
    start_sec: float
    end_sec: float
    text: str


@dataclass(frozen=True)
class TranscriptChunk:  # noqa: D101
    start_sec: float
    end_sec: float
    text: str
    segments: tuple[TranscriptSegment, ...]


# --- Estimation helpers ---


def _default_estimator() -> TokenEstimator:
    adapter = GeminiEstimationAdapter()

    def estimate(text: str) -> int:
        src = Source.from_text(text)
        est = adapter.estimate(src)
        return max(int(est.expected_tokens), 0)

    return estimate


def _estimate_tokens(text: str, estimator: TokenEstimator | None) -> int:
    est = estimator or _default_estimator()
    try:
        return max(int(est(text)), 0)
    except Exception:
        # Very conservative fallback: ~4 chars/token, plus a floor
        return max(len(text) // 4, 1)


# --- Text chunking ---


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def chunk_text_by_tokens(
    text: str,
    *,
    target_tokens: int = 8000,
    overlap_tokens: int = 200,
    max_chunks: int | None = None,
    estimator: TokenEstimator | None = None,
) -> list[str]:
    r"""Chunk plain text into approximate token-bounded chunks.

    Strategy:
    - Prefer paragraph boundaries (\n\n) then sentence boundaries as needed.
    - Accumulate units until adding the next would exceed target; if a single
      unit is larger than target, split it by sentences or raw slices.
    - Include token overlap across chunk boundaries by reusing a tail from
      the previous chunk.
    """
    if not text.strip():
        return []
    target_tokens = max(int(target_tokens), 1)
    overlap_tokens = max(int(overlap_tokens), 0)

    parts = [p for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        chunk_text = "\n\n".join(current).strip()
        if chunk_text:
            # Apply approximate overlap to next chunk by carrying tail tokens
            chunks.append(chunk_text)
        current = []
        current_tokens = 0

    def add_unit(unit_text: str) -> None:
        nonlocal current_tokens
        t = _estimate_tokens(unit_text, estimator)
        if current_tokens + t <= target_tokens or not current:
            current.append(unit_text)
            current_tokens += t
        else:
            flush()
            current.append(unit_text)
            current_tokens = t

    for para in parts:
        ptok = _estimate_tokens(para, estimator)
        if ptok > target_tokens:
            # Split paragraph by sentences
            sentences = _SENTENCE_SPLIT_RE.split(para)
            if len(sentences) == 1:
                # Hard split by characters as last resort
                add_unit(para[: max(1, len(para) // 2)])
                add_unit(para[max(1, len(para) // 2) :])
                continue
            for sent in sentences:
                if not sent.strip():
                    continue
                stok = _estimate_tokens(sent, estimator)
                if stok > target_tokens:
                    # Hard split very long sentence
                    mid = max(1, len(sent) // 2)
                    add_unit(sent[:mid])
                    add_unit(sent[mid:])
                else:
                    add_unit(sent)
        else:
            add_unit(para)

        if max_chunks is not None and len(chunks) >= max_chunks:
            break

    flush()

    if overlap_tokens > 0 and len(chunks) > 1:
        # Rebuild with overlap tails
        with_overlap: list[str] = []
        prev_tail = ""
        for i, c in enumerate(chunks):
            if i == 0:
                with_overlap.append(c)
            else:
                merged = (prev_tail + "\n\n" + c).strip() if prev_tail else c
                with_overlap.append(merged)
            # Compute next overlap tail from current chunk end (approximate by words)
            words = c.split()
            # Approximate 1 token ~ 1 word for tail extraction
            tail_words = max(min(overlap_tokens, len(words)), 0)
            prev_tail = " ".join(words[-tail_words:]) if tail_words else ""
        chunks = with_overlap

    if max_chunks is not None:
        chunks = chunks[:max_chunks]
    return chunks


# --- Transcript chunking ---


def chunk_transcript_by_tokens(
    segments: Iterable[TranscriptSegment],
    *,
    target_tokens: int = 8000,
    overlap_tokens: int = 200,
    max_chunks: int | None = None,
    estimator: TokenEstimator | None = None,
) -> list[TranscriptChunk]:
    """Chunk transcripts (time-stamped segments) into token-bounded chunks.

    Overlap is achieved by re-including trailing segments sufficient to
    approximate the requested token overlap.
    """
    segs = [s for s in segments if s.text.strip()]
    if not segs:
        return []
    target_tokens = max(int(target_tokens), 1)
    overlap_tokens = max(int(overlap_tokens), 0)

    chunks: list[TranscriptChunk] = []
    cur: list[TranscriptSegment] = []
    cur_tokens = 0

    def flush() -> None:
        nonlocal cur, cur_tokens
        if not cur:
            return
        txt = " ".join(s.text for s in cur).strip()
        chunks.append(
            TranscriptChunk(
                start_sec=cur[0].start_sec,
                end_sec=cur[-1].end_sec,
                text=txt,
                segments=tuple(cur),
            )
        )
        cur = []
        cur_tokens = 0

    for s in segs:
        t = _estimate_tokens(s.text, estimator)
        if cur_tokens + t <= target_tokens or not cur:
            cur.append(s)
            cur_tokens += t
        else:
            flush()
            cur.append(s)
            cur_tokens = t

        if max_chunks is not None and len(chunks) >= max_chunks:
            break

    flush()

    # Apply segment-based overlap by re-including trailing segments
    if overlap_tokens > 0 and len(chunks) > 1:
        overlapped: list[TranscriptChunk] = []
        carry: list[TranscriptSegment] = []
        carry_tokens = 0
        for i, ch in enumerate(chunks):
            if i == 0:
                overlapped.append(ch)
            else:
                # Prepend carried segments to current chunk
                merged_segments = tuple(carry) + ch.segments
                txt = " ".join(s.text for s in merged_segments)
                overlapped.append(
                    TranscriptChunk(
                        start_sec=merged_segments[0].start_sec,
                        end_sec=merged_segments[-1].end_sec,
                        text=txt,
                        segments=merged_segments,
                    )
                )
            # Prepare carry from tail of current chunk
            carry = []
            carry_tokens = 0
            for s in reversed(ch.segments):
                tok = _estimate_tokens(s.text, estimator)
                if carry_tokens + tok > overlap_tokens and carry:
                    break
                carry.insert(0, s)
                carry_tokens += tok
        chunks = overlapped

    if max_chunks is not None:
        chunks = chunks[:max_chunks]
    return chunks
