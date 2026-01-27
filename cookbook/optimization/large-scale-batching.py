#!/usr/bin/env python3
"""🎯 Recipe: Large-Scale Batching with Bounded Concurrency

When you need to: Ask the same question over many sources with client-side
fan-out and a safe concurrency limit.

Ingredients:
- A directory with many files
- `GEMINI_API_KEY` in environment

What you'll learn:
- Use `run_parallel` to fan out per-source calls
- Bound concurrency to respect rate/throughput
- Inspect aggregate status and metrics

Difficulty: ⭐⭐⭐
Time: ~10-12 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from cookbook.utils.demo_inputs import (
    DEFAULT_TEXT_DEMO_DIR,
    pick_files_by_ext,
)
from pollux import types
from pollux.frontdoor import run_parallel


async def main_async(
    directory: Path, prompt: str, concurrency: int, limit: int = 2
) -> None:
    files = pick_files_by_ext(
        directory,
        [".pdf", ".txt", ".png", ".jpg", ".jpeg", ".mp4", ".mov"],
        limit=limit,
    )
    sources = tuple(types.Source.from_file(p) for p in files)
    if not sources:
        raise SystemExit(f"No files found under {directory}")

    env = await run_parallel(
        prompt, sources, prefer_json=False, concurrency=concurrency
    )
    print(f"Status: {env.get('status', 'ok')}")
    metrics = env.get("metrics", {})
    if isinstance(metrics, dict):
        print(f"Parallel calls: {metrics.get('parallel_n_calls')}")
        if metrics.get("parallel_errors"):
            print(f"Errors: {metrics.get('parallel_errors')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Large-scale batching with concurrency"
    )
    parser.add_argument("--input", type=Path, default=None, help="Directory of files")
    parser.add_argument("--limit", type=int, default=2, help="Max files to read")
    parser.add_argument(
        "--prompt",
        default="Extract three key takeaways.",
        help="Question to ask each source",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max client-side fan-out",
    )
    parser.add_argument("--data-dir", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    directory = args.input or args.data_dir or DEFAULT_TEXT_DEMO_DIR
    if not directory.exists():
        raise SystemExit("No input provided. Run `make demo-data` or pass --input.")
    print("Note: File size/count affect runtime and tokens.")
    asyncio.run(
        main_async(directory, args.prompt, args.concurrency, max(1, int(args.limit)))
    )


if __name__ == "__main__":
    main()
