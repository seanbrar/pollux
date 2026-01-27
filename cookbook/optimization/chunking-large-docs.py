#!/usr/bin/env python3
"""🎯 Recipe: Chunk Very Large Documents and Merge Answers.

When you need to: Analyze long documents that exceed context limits by
segmenting them into token-aware chunks, processing each, then merging results.

Ingredients:
- One or more large text files (for PDFs, pre-extract text via your tool of choice)
- A merge strategy (summary-of-summaries or simple concatenation)

What you'll learn:
- Token-aware segmentation via `extensions.chunking`
- Batch over chunks and collect per-chunk diagnostics
- Merge strategies and tradeoffs

Difficulty: ⭐⭐⭐⭐
Time: ~12-18 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from cookbook.utils.demo_inputs import (
    DEFAULT_TEXT_DEMO_DIR,
    resolve_file_or_exit,
)
from cookbook.utils.retry import retry_async
from pollux import types
from pollux.extensions.chunking import chunk_text_by_tokens
from pollux.frontdoor import run_batch, run_parallel

if TYPE_CHECKING:
    from pollux.core.result_envelope import ResultEnvelope


def _read_text(path: Path) -> str:
    # For PDFs, run OCR/extraction beforehand; here we assume UTF-8 text files
    return path.read_text(encoding="utf-8", errors="ignore")


def _chunks_from_text(text: str, target_tokens: int) -> list[str]:
    # Use token-based chunking
    return chunk_text_by_tokens(text, target_tokens=target_tokens)


async def _analyze_chunks(
    chunks: list[str], prompt: str, concurrency: int
) -> list[str]:
    # Prefer parallel fan-out for performance when >1
    sources = tuple(
        types.Source.from_text(ch, identifier=f"chunk-{idx}")
        for idx, ch in enumerate(chunks)
    )
    total = len(sources)
    if concurrency and concurrency > 1:
        print(f"Analyzing {total} chunks with concurrency={concurrency}...")
        env = await retry_async(
            lambda: run_parallel(prompt, sources, concurrency=concurrency),
            retries=3,
            initial_delay=1.0,
            backoff=2.0,
        )
        ans = env.get("answers", [])
        return [str(a) for a in ans]
    # Fallback: sequential batch per chunk
    out: list[str] = []
    print(f"Analyzing {total} chunks sequentially (concurrency=1)...")
    for i, src in enumerate(sources, start=1):
        if i == 1 or i % 5 == 0 or i == total:
            print(f"  • chunk {i}/{total} ...")

        async def _call(s: types.Source = src) -> ResultEnvelope:
            return await run_batch([prompt], [s])

        env = await retry_async(_call, retries=3, initial_delay=1.0, backoff=2.0)
        a = env.get("answers", [])
        out.append(str(a[0]) if a else "")
    return out


def _merge(answers: list[str]) -> str:
    # Simple summary-of-summaries: ask one final question over concatenated answers
    return "\n\n".join(answers)


async def main_async(
    path: Path, target_tokens: int, prompt: str, concurrency: int
) -> None:
    text = _read_text(path)
    chunks = _chunks_from_text(text, target_tokens)
    print(f"✂️  Created {len(chunks)} chunks (~{target_tokens} tokens each target)")

    per = await _analyze_chunks(chunks, prompt, concurrency)
    merged = _merge(per)
    print("\n📋 Consolidated answer (first 500 chars):\n")
    print(merged[:500] + ("..." if len(merged) > 500 else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk large docs and merge answers")
    parser.add_argument("path", type=Path, nargs="?", help="Path to a large text file")
    parser.add_argument(
        "--target-tokens",
        type=int,
        default=9000,
        help=(
            "Target tokens per chunk (demo default: 9k). Increase/decrease to balance speed vs granularity."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Parallel fan-out across chunks (1 = sequential)",
    )
    parser.add_argument(
        "--prompt",
        default="Summarize the key insights and provide 3 bullets of recommendations.",
        help="Prompt to apply to each chunk",
    )
    args = parser.parse_args()

    # Resolve input: prefer provided path, else demo text pack (input.txt)
    path = resolve_file_or_exit(
        args.path if isinstance(args.path, Path) else None,
        search_dir=DEFAULT_TEXT_DEMO_DIR,
        exts=(".txt", ".md"),
        hint=("No input provided. Run `make demo-data` or pass a text file path."),
    )
    asyncio.run(main_async(path, args.target_tokens, args.prompt, args.concurrency))


if __name__ == "__main__":
    main()
