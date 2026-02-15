#!/usr/bin/env python3
"""Template: Scenario-first cookbook recipe.

Copy this file when creating a new recipe, then replace placeholders in:
- Problem framing
- Prompt set
- Success checks and output interpretation
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, resolve_dir_or_exit
from cookbook.utils.presentation import (
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
)
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
)
from pollux import Config, Source, run_many

PROMPTS = ["[Replace with a concrete prompt]"]


async def main_async(directory: Path, *, limit: int, config: Config) -> None:
    files = sorted(path for path in directory.rglob("*") if path.is_file())[:limit]
    if not files:
        raise SystemExit(f"No files found under: {directory}")

    sources = [Source.from_file(path) for path in files]
    envelope = await run_many(PROMPTS, sources=sources, config=config)

    print_section("Result")
    print_kv_rows(
        [
            ("Status", envelope.get("status", "ok")),
            ("Answers", len(envelope.get("answers", []))),
        ]
    )
    print_learning_hints(
        [
            "Next: replace placeholder prompts with explicit output constraints.",
            "Next: define what good output looks like for this scenario before scaling.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Template cookbook recipe")
    parser.add_argument("--input", type=Path, default=None, help="Directory of files")
    parser.add_argument("--limit", type=int, default=2, help="Max files to include")
    add_runtime_args(parser)
    args = parser.parse_args()

    directory = resolve_dir_or_exit(
        args.input,
        DEFAULT_TEXT_DEMO_DIR,
        hint="No input directory found. Run `make demo-data` or pass --input /path/to/dir.",
    )
    config = build_config_or_exit(args)

    print_header("Template recipe", config=config)
    asyncio.run(main_async(directory, limit=max(1, int(args.limit)), config=config))


if __name__ == "__main__":
    main()
