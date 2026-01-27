#!/usr/bin/env python3
"""🎯 Recipe: Comparative Analysis Across Sources

When you need to: Compare two or more documents side-by-side for similarities,
differences, strengths, and weaknesses.

Ingredients:
- 2+ files to compare
- `GEMINI_API_KEY` in environment

What you'll learn:
- Use a single prompt to drive a structured comparison
- Prefer JSON and parse defensively
- Print a concise diff summary

Difficulty: ⭐⭐⭐
Time: ~10 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path

from cookbook.utils.json_tools import coerce_json
from pollux import types
from pollux.frontdoor import run_batch

PROMPT = (
    "Return application/json ONLY. Compare the sources and output a compact JSON object "
    "with keys: similarities (list), differences (list), strengths (list), weaknesses (list). "
    "Do not include markdown or commentary."
)


@dataclass
class Comparison:
    similarities: list[str]
    differences: list[str]
    strengths: list[str]
    weaknesses: list[str]


def _parse(answer: str) -> Comparison | None:
    data = coerce_json(answer)
    if not isinstance(data, dict):
        return None
    return Comparison(
        similarities=[str(x) for x in data.get("similarities", [])],
        differences=[str(x) for x in data.get("differences", [])],
        strengths=[str(x) for x in data.get("strengths", [])],
        weaknesses=[str(x) for x in data.get("weaknesses", [])],
    )


async def main_async(paths: list[Path]) -> None:
    srcs = [types.Source.from_file(p) for p in paths]
    env = await run_batch([PROMPT], srcs, prefer_json=True)
    ans = (env.get("answers") or [""])[0]
    comp = _parse(str(ans))
    if comp:
        print("\n✅ Comparison Summary")
        print(
            f"• Similarities: {len(comp.similarities)} | Differences: {len(comp.differences)}"
        )
        print(
            f"• Strengths: {len(comp.strengths)} | Weaknesses: {len(comp.weaknesses)}"
        )
        if comp.differences:
            print("\nFirst difference:")
            print(f"- {comp.differences[0]}")
    else:
        print("\n⚠️ Could not parse JSON; raw (first 400 chars):\n")
        print(str(ans)[:400])


def main() -> None:
    parser = argparse.ArgumentParser(description="Comparative analysis across sources")
    parser.add_argument(
        "paths", type=Path, nargs="*", default=[], help="Files to compare"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Directory to search if fewer than 2 paths provided",
    )
    args = parser.parse_args()
    paths: list[Path] = list(args.paths)
    if len(paths) < 2:
        data_dir = args.input or Path("cookbook/data/demo/text-medium")
        if not data_dir.exists():
            raise SystemExit(
                "Need two files. Run `make demo-data` or pass two paths/--input."
            )
        exts = {".pdf", ".txt", ".jpg", ".png", ".md"}
        candidates: list[tuple[int, Path]] = []
        for p in data_dir.rglob("*"):
            try:
                if p.is_file() and p.suffix.lower() in exts:
                    candidates.append((p.stat().st_size, p))
            except OSError:
                continue
        candidates.sort(key=lambda x: x[0])
        if len(candidates) < 2:
            raise SystemExit(
                f"Need at least two files under {data_dir} or pass explicit paths"
            )
        paths = [candidates[0][1], candidates[1][1]]
    print("Note: File size/count affect runtime and tokens.")
    asyncio.run(main_async(paths))


if __name__ == "__main__":
    main()
