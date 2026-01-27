#!/usr/bin/env python3
"""🎯 Recipe: Rate Limits and Request Concurrency

When you need to: Understand how tier constraints and `request_concurrency`
affect vectorized execution, and compare sequential vs bounded fan-out.

Ingredients:
- A directory with a few files (2-6) or one large file with multiple prompts
- `GEMINI_API_KEY` set in the environment

What you'll learn:
- Override per-call `request_concurrency` using `make_execution_options`
- Observe `metrics.concurrency_used` and per-call meta timings
- Behavior with and without constraints (illustrative; provider limits apply)

Difficulty: ⭐⭐⭐
Time: ~10 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from cookbook.utils.demo_inputs import (
    DEFAULT_TEXT_DEMO_DIR,
    pick_files_by_ext,
)
from pollux import types
from pollux.frontdoor import run_batch
from pollux.types import make_execution_options

if TYPE_CHECKING:
    from pollux.core.result_envelope import ResultEnvelope


def _summ(env: ResultEnvelope) -> None:
    m = env.get("metrics") or {}
    answers = env.get("answers", [])
    print(f"Answers: {len(answers)} | concurrency_used: {m.get('concurrency_used')}")
    per = m.get("per_call_meta") or ()
    if per:
        print("  per_call_meta (first 3):")
        for i, meta in enumerate(per[:3]):
            dur = meta.get("duration_s")
            api = meta.get("api_time_s")
            non = meta.get("non_api_time_s")
            print(f"   - call[{i}]: duration={dur}, api={api}, non_api={non}")


async def main_async(directory: Path, concurrency: int, limit: int = 2) -> None:
    prompts = [
        "Identify 3 key facts.",
        "List main entities.",
        "Summarize in 3 bullets.",
    ]
    files = pick_files_by_ext(directory, [".pdf", ".txt"], limit=limit)
    sources = tuple(types.Source.from_file(p) for p in files)
    if not sources:
        raise SystemExit(f"No files found under {directory}")

    opts_seq = make_execution_options(request_concurrency=1)
    opts_bounded = make_execution_options(request_concurrency=max(1, concurrency))

    print("\n⏱️  Sequential (concurrency=1)")
    seq = await run_batch(prompts, sources, options=opts_seq)
    _summ(seq)

    print("\n⚡ Bounded fan-out (concurrency=", max(1, concurrency), ")", sep="")
    par = await run_batch(prompts, sources, options=opts_bounded)
    _summ(par)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rate limits & concurrency demo")
    parser.add_argument("--input", type=Path, default=None, help="Directory with files")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--limit", type=int, default=2, help="Max files to read")
    parser.add_argument("--data-dir", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    directory = args.input or args.data_dir or DEFAULT_TEXT_DEMO_DIR
    if not directory.exists():
        raise SystemExit("No input provided. Run `make demo-data` or pass --input.")
    print("Note: File size/count affect runtime and tokens.")
    asyncio.run(main_async(directory, args.concurrency, max(1, int(args.limit))))


if __name__ == "__main__":
    main()
