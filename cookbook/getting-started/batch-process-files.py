#!/usr/bin/env python3
"""🎯 Recipe: Batch Process Multiple Files Efficiently.

When you need to: Run a few questions across a directory of files in one go.

Ingredients:
- A directory of files (PDF, text, image, audio, video)
- `GEMINI_API_KEY` set in the environment

What you'll learn:
- Build `Source` objects from a directory
- Vectorize prompts via `run_batch`
- Inspect answers and per-prompt metrics

Difficulty: ⭐⭐
Time: ~8 minutes
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

if TYPE_CHECKING:
    from pollux.core.result_envelope import ResultEnvelope


def _print_summary(env: ResultEnvelope) -> None:
    answers = env.get("answers", [])
    metrics = env.get("metrics", {})
    usage = env.get("usage", {})
    print(f"Answers returned: {len(answers)}")
    if isinstance(usage, dict):
        tok = usage.get("total_token_count")
        if tok is not None:
            print(f"🔢 Total tokens: {tok}")
    if isinstance(metrics, dict) and metrics.get("per_prompt"):
        print("\n⏱️  Per-prompt snapshots:")
        for p in metrics["per_prompt"]:
            idx = p.get("index")
            dur = (p.get("durations") or {}).get("execute.total")
            print(f"  Prompt[{idx}] duration: {dur if dur is not None else 'N/A'}s")


async def main_async(directory: Path, limit: int) -> None:
    prompts = [
        "List 3 key takeaways.",
        "Extract the main entities mentioned.",
    ]
    files = pick_files_by_ext(
        directory,
        [".pdf", ".txt", ".png", ".jpg", ".jpeg", ".mp4", ".mov"],
        limit=limit,
    )
    sources = tuple(types.Source.from_file(p) for p in files)
    if not sources:
        raise SystemExit(f"No files found under {directory}")

    env = await run_batch(prompts, sources, prefer_json=False)
    print(f"Status: {env.get('status', 'ok')}")
    _print_summary(env)


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch process multiple files")
    parser.add_argument("--input", type=Path, default=None, help="Directory of files")
    parser.add_argument("--limit", type=int, default=2, help="Max files to read")
    args = parser.parse_args()
    if args.input is not None:
        directory = args.input
    else:
        directory = DEFAULT_TEXT_DEMO_DIR
        if not directory.exists():
            raise SystemExit("No input provided. Run `make demo-data` or pass --input.")
    print("Note: File size/count affect runtime and tokens.")
    asyncio.run(main_async(directory, max(1, int(args.limit))))


if __name__ == "__main__":
    main()
