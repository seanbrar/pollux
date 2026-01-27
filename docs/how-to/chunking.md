# Chunking (Extension)

Last reviewed: 2025-09

Goal: Split long text or transcripts into chunks that fit approximate token budgets, so you can prompt efficiently and control context size.

When to use: Preparing long sources (articles, transcripts, logs) for prompting or conversation flows, especially when you need overlap for continuity.

Prerequisites

- Python 3.13, repository set up with `make install-dev`.
- No real API required; chunking uses planner‑aligned estimation heuristics locally.

## 1) Chunk text by approximate tokens

This example splits a sample text file into ~2000‑token chunks with ~200‑token overlap.

```python title="chunk_text.py"
from pathlib import Path
from pollux.extensions import chunk_text_by_tokens

text_path = Path("cookbook/data/public/sample.txt")
text = text_path.read_text(encoding="utf-8")

chunks = chunk_text_by_tokens(
    text,
    target_tokens=2000,
    overlap_tokens=200,
)

print(f"Chunks: {len(chunks)}")
print("First chunk preview:\n", chunks[0][:400])

assert len(chunks) >= 1
```

Notes

- Token counts are approximate (heuristic estimator aligned with the planner’s Gemini adapter). Real token usage may differ slightly.
- Overlap is applied approximately across chunk boundaries by carrying tail words forward.

## 2) Optional: Use chunks with the Conversation extension

Summarize each chunk with a single prompt per chunk using mock mode by default (no real API required). Set `POLLUX_USE_REAL_API=1` if you want real calls.

```python title="summarize_chunks.py"
import asyncio
from pathlib import Path
from pollux import create_executor, types
from pollux.extensions import Conversation, chunk_text_by_tokens

async def main() -> None:
    text = Path("cookbook/data/public/sample.txt").read_text(encoding="utf-8")
    chunks = chunk_text_by_tokens(text, target_tokens=2000, overlap_tokens=200)

    ex = create_executor()  # mock by default unless env enables real API
    conv = Conversation.start(ex)

    summaries: list[str] = []
    for idx, ch in enumerate(chunks, start=1):
        # Use one chunk as the only source for this turn
        src = types.Source.from_text(ch)
        conv = conv.with_sources([src])
        conv = await conv.ask(f"Summarize chunk {idx} in 1-2 sentences.")
        summaries.append(conv.state.turns[-1].assistant)

    print("First summary:\n", summaries[0][:400])

asyncio.run(main())
```

Tips

- For reproducible demos, keep outputs short and ground prompts in the provided chunk.
- If throttled on real API, set `POLLUX_TIER` to match billing or reduce concurrency via config.

## 3) Chunk transcripts by approximate tokens

Split a time‑stamped transcript while preserving segments and timestamps.

```python title="chunk_transcript.py"
from pollux.extensions import (
    TranscriptSegment,
    chunk_transcript_by_tokens,
)

segments = [
    TranscriptSegment(0.0, 2.0, "Hello and welcome to our session."),
    TranscriptSegment(2.0, 5.0, "Today we'll discuss batching strategies."),
    TranscriptSegment(5.0, 8.5, "We'll also cover token budgeting and overlap."),
]

chunks = chunk_transcript_by_tokens(
    segments,
    target_tokens=30,
    overlap_tokens=10,
)

for i, ch in enumerate(chunks, start=1):
    print(f"Chunk {i}: {ch.start_sec:.1f}s → {ch.end_sec:.1f}s; segments={len(ch.segments)}")

assert len(chunks) >= 1
```

Validation and troubleshooting

- If you get zero chunks, verify the input is non‑empty and `target_tokens >= 1`.
- If a single paragraph/segment exceeds `target_tokens`, the functions fall back to sentence or character splits.
- Token estimates are a guide; use [Token Counting](token-counting.md) when you need the exact Gemini tokenizer count.

See also

- API Reference: [Chunking Extension](../reference/api/extensions/chunking.md)
- Token Counting (Extension): [how-to/token-counting.md](token-counting.md)
- Custom Transforms: [how-to/custom-transforms.md](custom-transforms.md)
