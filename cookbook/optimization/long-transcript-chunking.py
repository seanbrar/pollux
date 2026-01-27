#!/usr/bin/env python3
"""🎯 Recipe: Long Transcript Chunking + Simple Stitching

When you need to: Process a long transcript (e.g., a talk or lecture) by
chunking it into token-bounded segments with timestamps, then stitch answers
into a consolidated summary.

Ingredients:
- A transcript text file (one sentence per line is fine)
- `GEMINI_API_KEY` set in the environment

What you'll learn:
- Use `chunk_transcript_by_tokens` to produce time-aware chunks
- Batch over chunks and collect per-chunk answers
- Stitch outputs with a simple reducer (concat or summary-of-summaries)

Difficulty: ⭐⭐⭐
Time: ~10-12 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from cookbook.utils.demo_inputs import (
    DEFAULT_TEXT_DEMO_DIR,
    resolve_file_or_exit,
)
from pollux import types
from pollux.extensions.chunking import (
    TranscriptChunk,
    TranscriptSegment,
    chunk_transcript_by_tokens,
)
from pollux.frontdoor import run_batch, run_parallel


def _read_lines(path: Path) -> list[str]:
    txt = path.read_text(encoding="utf-8", errors="ignore")
    return [ln.strip() for ln in txt.splitlines() if ln.strip()]


def _as_segments(lines: list[str], step_sec: int = 10) -> list[TranscriptSegment]:
    segs: list[TranscriptSegment] = []
    t = 0.0
    for ln in lines:
        start = t
        end = t + step_sec
        segs.append(TranscriptSegment(start, end, ln))
        t = end
    return segs


async def _analyze(
    chunks: list[TranscriptChunk], prompt: str, concurrency: int
) -> list[str]:
    sources = tuple(
        types.Source.from_text(
            ch.text, identifier=f"chunk-{idx} [{ch.start_sec:.0f}-{ch.end_sec:.0f}s]"
        )
        for idx, ch in enumerate(chunks)
    )
    if concurrency and concurrency > 1:
        env = await run_parallel(prompt, sources, concurrency=concurrency)
        ans = env.get("answers", [])
        return [str(a) for a in ans]
    out: list[str] = []
    for src in sources:
        env = await run_batch([prompt], [src])
        ans = env.get("answers", [])
        out.append(str(ans[0]) if ans else "")
    return out


def _stitch(per_chunk: list[str]) -> str:
    return "\n\n".join(per_chunk)


async def main_async(
    path: Path, target_tokens: int, prompt: str, concurrency: int
) -> None:
    lines = _read_lines(path)
    segs = _as_segments(lines)
    chunks = chunk_transcript_by_tokens(
        segs, target_tokens=target_tokens, overlap_tokens=150
    )
    print(f"✂️  Created {len(chunks)} chunks (~{target_tokens} tokens target)")
    per = await _analyze(chunks, prompt, concurrency)
    merged = _stitch(per)
    print("\n📋 Consolidated answer (first 700 chars):\n")
    print(merged[:700] + ("..." if len(merged) > 700 else ""))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chunk long transcripts and stitch answers"
    )
    parser.add_argument(
        "path", type=Path, nargs="?", help="Path to transcript text file"
    )
    parser.add_argument("--target-tokens", type=int, default=1200)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Parallel fan-out across chunks (1 = sequential)",
    )
    parser.add_argument(
        "--prompt",
        default="Summarize the key insights and provide 5 bullets of recommendations.",
    )
    args = parser.parse_args()
    path = resolve_file_or_exit(
        args.path if isinstance(args.path, Path) else None,
        search_dir=DEFAULT_TEXT_DEMO_DIR,
        exts=(".txt", ".md"),
        hint=(
            "No input provided. Run `make demo-data` or pass a transcript .txt file."
        ),
    )
    asyncio.run(main_async(path, args.target_tokens, args.prompt, args.concurrency))


if __name__ == "__main__":
    main()
