#!/usr/bin/env python3
"""Recipe: Compare two sources with structured JSON output.

Problem:
    You need side-by-side similarities and differences across documents.

Pattern:
    - Request strict JSON from the model.
    - Parse defensively.
    - Print a compact decision-ready summary.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path

from cookbook.utils.json_tools import coerce_json
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
    print_run_mode,
)
from pollux import Config, Source, batch

PROMPT = (
    "Return application/json only with keys: similarities (list), differences (list), "
    "strengths (list), weaknesses (list)."
)


@dataclass
class Comparison:
    similarities: list[str]
    differences: list[str]
    strengths: list[str]
    weaknesses: list[str]


def parse_comparison(raw: str) -> Comparison | None:
    """Parse robust JSON model output into comparison object."""
    data = coerce_json(raw)
    if not isinstance(data, dict):
        return None

    def as_list(name: str) -> list[str]:
        value = data.get(name, [])
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    return Comparison(
        similarities=as_list("similarities"),
        differences=as_list("differences"),
        strengths=as_list("strengths"),
        weaknesses=as_list("weaknesses"),
    )


def pick_default_pair(directory: Path) -> list[Path]:
    """Select two deterministic files from a directory."""
    candidates = sorted(path for path in directory.rglob("*") if path.is_file())
    if len(candidates) < 2:
        raise SystemExit(f"Need at least two files under: {directory}")
    return candidates[:2]


async def main_async(paths: list[Path], *, config: Config) -> None:
    sources = [Source.from_file(path) for path in paths]
    envelope = await batch([PROMPT], sources=sources, config=config)

    answer = str((envelope.get("answers") or [""])[0])
    parsed = parse_comparison(answer)

    print("\nComparative analysis")
    print(f"- Status: {envelope.get('status', 'ok')}")
    print(f"- Sources: {', '.join(str(path) for path in paths)}")

    if parsed is None:
        excerpt = answer[:400] + ("..." if len(answer) > 400 else "")
        print("- Could not parse JSON. Raw excerpt:")
        print(excerpt)
        return

    print(
        "- Counts: "
        f"similarities={len(parsed.similarities)} "
        f"differences={len(parsed.differences)} "
        f"strengths={len(parsed.strengths)} "
        f"weaknesses={len(parsed.weaknesses)}"
    )
    if parsed.differences:
        print(f"- First key difference: {parsed.differences[0]}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Produce a structured source-to-source comparison.",
    )
    parser.add_argument("paths", type=Path, nargs="*", help="Two input files")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("cookbook/data/demo/text-medium"),
        help="Fallback directory when fewer than two paths are provided.",
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    paths = list(args.paths)
    if len(paths) < 2:
        if not args.input.exists():
            raise SystemExit(
                "Need two files. Run `make demo-data` or provide two explicit paths."
            )
        paths = pick_default_pair(args.input)

    config = build_config_or_exit(args)
    print("Research comparison baseline")
    print_run_mode(config)
    asyncio.run(main_async(paths[:2], config=config))


if __name__ == "__main__":
    main()
