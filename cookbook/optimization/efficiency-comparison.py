#!/usr/bin/env python3
"""🎯 Recipe: Efficiency Comparison — Vectorized vs Naive

When you need to: Quantify token/time savings of vectorized prompts over a
shared context compared to a naive loop that calls once per prompt.

Ingredients:
- A directory of files or one file with multiple prompts
- `GEMINI_API_KEY` set in the environment

What you'll learn:
- Use `research.compare_efficiency` to benchmark both paths
- Interpret tokens/time/call ratios and basic environment capture
- Optional aggregate mode for single-call multi-answer JSON

Difficulty: ⭐⭐
Time: ~8-10 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Literal

from cookbook.utils.demo_inputs import (
    DEFAULT_TEXT_DEMO_DIR,
    pick_files_by_ext,
)
from pollux import types
from pollux.research import compare_efficiency


async def main_async(directory: Path, mode: str, trials: int, limit: int = 2) -> None:
    prompts = [
        "List 3 key takeaways.",
        "Extract top entities.",
        "Summarize in 3 bullets.",
    ]
    files = pick_files_by_ext(
        directory, [".pdf", ".txt", ".png", ".jpg", ".jpeg"], limit=limit
    )
    sources = tuple(types.Source.from_file(p) for p in files)

    def _normalize_mode(m: str) -> Literal["batch", "aggregate", "auto"]:
        return (
            "batch" if m == "batch" else ("aggregate" if m == "aggregate" else "auto")
        )

    rep = await compare_efficiency(
        prompts,
        sources,
        prefer_json=(mode == "aggregate"),
        mode=_normalize_mode(mode),
        trials=max(1, trials),
        warmup=1,
        include_pipeline_durations=True,
        label="cookbook-demo",
    )
    print("\n📊 Efficiency Summary:")
    print(rep.summary(verbose=(trials > 1)))
    # Optional: print environment and call counts
    print("Env:", rep.env)


def main() -> None:
    parser = argparse.ArgumentParser(description="Efficiency comparison demo")
    parser.add_argument("--input", type=Path, default=None, help="Directory with files")
    parser.add_argument(
        "--mode",
        choices=["batch", "aggregate", "auto"],
        default="auto",
        help="Vectorized mode: multi-call batch vs single-call aggregate",
    )
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--limit", type=int, default=2, help="Max files to read")
    # Deprecated
    parser.add_argument("--data-dir", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    directory = args.input or args.data_dir or DEFAULT_TEXT_DEMO_DIR
    if not directory.exists():
        raise SystemExit("No input provided. Run `make demo-data` or pass --input.")
    print("Note: File size/count affect runtime and tokens.")
    asyncio.run(main_async(directory, args.mode, args.trials, max(1, int(args.limit))))


if __name__ == "__main__":
    main()
