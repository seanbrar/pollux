#!/usr/bin/env python3
"""🎯 Recipe: Content Assessment for Learning Objectives

When you need to: Evaluate course materials (slides, PDFs, notes) for clarity,
coverage, difficulty, and alignment to learning objectives.

Ingredients:
- A directory of course materials
- `GEMINI_API_KEY` in environment

What you'll learn:
- Create assessment criteria prompts
- Prefer JSON for structured rubrics
- Print improvement suggestions

Note:
- This recipe uses a tiny helper (`cookbook.utils.json_tools.coerce_json`) to
  parse JSON robustly even when models wrap output in Markdown code fences or
  include minor formatting. This keeps the narrative simple while being
  transparent about the parsing step.

Difficulty: ⭐⭐⭐
Time: ~10-12 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path

from cookbook.utils.demo_inputs import (
    DEFAULT_TEXT_DEMO_DIR,
    pick_files_by_ext,
)
from cookbook.utils.json_tools import coerce_json
from pollux import types
from pollux.frontdoor import run_batch

PROMPT = (
    "Assess these materials and return JSON with keys: "
    "clarity (1-5), coverage (1-5), difficulty (1-5), alignment (1-5), "
    "strengths (list), improvements (list)."
)


@dataclass
class Assessment:
    clarity: int
    coverage: int
    difficulty: int
    alignment: int
    strengths: list[str]
    improvements: list[str]


def _parse(answer: str) -> Assessment | None:
    data = coerce_json(answer)
    if not isinstance(data, dict):
        return None
    try:
        return Assessment(
            clarity=int(data.get("clarity", 0)),
            coverage=int(data.get("coverage", 0)),
            difficulty=int(data.get("difficulty", 0)),
            alignment=int(data.get("alignment", 0)),
            strengths=[str(s) for s in data.get("strengths", [])],
            improvements=[str(s) for s in data.get("improvements", [])],
        )
    except Exception:
        return None


async def main_async(directory: Path, limit: int = 2) -> None:
    files = pick_files_by_ext(directory, [".pdf", ".txt"], limit=limit)
    srcs = tuple(types.Source.from_file(p) for p in files)
    if not srcs:
        raise SystemExit(f"No files found under {directory}")
    env = await run_batch([PROMPT], srcs, prefer_json=True)
    ans = (env.get("answers") or [""])[0]
    a = _parse(str(ans))
    if a:
        print("\n✅ Assessment")
        print(
            f"Scores — clarity:{a.clarity} coverage:{a.coverage} difficulty:{a.difficulty} alignment:{a.alignment}"
        )
        if a.improvements:
            print("\nTop improvement suggestion:")
            print(f"- {a.improvements[0]}")
    else:
        print("\n⚠️ Could not parse JSON; raw (first 400 chars):\n")
        print(str(ans)[:400])


def main() -> None:
    parser = argparse.ArgumentParser(description="Assess course/lecture content")
    parser.add_argument(
        "--input", type=Path, default=None, help="Directory of materials"
    )
    parser.add_argument("--limit", type=int, default=2, help="Max files to read")
    args = parser.parse_args()
    directory = args.input or DEFAULT_TEXT_DEMO_DIR
    if not directory.exists():
        raise SystemExit("No input provided. Run `make demo-data` or pass --input.")
    print("Note: File size/count affect runtime and tokens.")
    asyncio.run(main_async(directory, max(1, int(args.limit))))


if __name__ == "__main__":
    main()
