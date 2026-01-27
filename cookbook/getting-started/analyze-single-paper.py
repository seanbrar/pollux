#!/usr/bin/env python3
"""🎯 Recipe: Analyze a Single Paper Quickly.

When you need to: Extract key insights from one document with a concise prompt.

Ingredients:
- One local file (PDF/TXT/PNG/MP4 supported by your model)
- `GEMINI_API_KEY` set in the environment

What you'll learn:
- Use `run_simple` for a one-off analysis
- Pass a `Source` from a file or text
- Inspect answer and basic usage metrics

Difficulty: ⭐
Time: ~5 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from cookbook.utils.demo_inputs import (
    DEFAULT_TEXT_DEMO_DIR,
    pick_file_by_ext,
)
from pollux import types
from pollux.frontdoor import run_simple


async def main_async(path: Path, prompt: str) -> None:
    src = types.Source.from_file(path)
    env = await run_simple(prompt, source=src, prefer_json=False)

    status = env.get("status", "ok")
    answers = env.get("answers", [])
    usage = env.get("usage", {})
    print(f"Status: {status}")
    if answers:
        print("\n📋 Answer (first 400 chars):\n")
        print(str(answers[0])[:400] + ("..." if len(str(answers[0])) > 400 else ""))
    if isinstance(usage, dict):
        tok = usage.get("total_token_count")
        if tok is not None:
            print(f"\n🔢 Tokens: {tok}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a single paper")
    parser.add_argument("--input", type=Path, default=None, help="Path to a file")
    parser.add_argument(
        "--prompt",
        default="Summarize the key ideas and contributions in 5 bullets.",
        help="Prompt/question to ask",
    )
    args = parser.parse_args()

    file_path: Path
    if args.input is not None:
        file_path = args.input
    else:
        demo_dir = DEFAULT_TEXT_DEMO_DIR
        if demo_dir.exists():
            pick = pick_file_by_ext(demo_dir, [".pdf", ".txt", ".png", ".jpg", ".mp4"])
            if pick is None:
                raise SystemExit(
                    "No suitable files found in demo dir. "
                    "Run `make demo-data` or pass --input."
                )
            file_path = pick
        else:
            raise SystemExit("No input provided. Run `make demo-data` or pass --input.")

    if not file_path.exists():
        raise SystemExit(f"File not found: {file_path}")
    print("Note: Larger files/more files take longer and use more tokens.")
    asyncio.run(main_async(file_path, args.prompt))


if __name__ == "__main__":
    main()
