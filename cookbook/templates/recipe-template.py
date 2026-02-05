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
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
    print_run_mode,
)
from pollux import Config, Source, batch

PROMPTS = ["[Replace with a concrete prompt]"]


async def main_async(directory: Path, *, limit: int, config: Config) -> None:
    files = sorted(path for path in directory.rglob("*") if path.is_file())[:limit]
    if not files:
        raise SystemExit(f"No files found under: {directory}")

    sources = [Source.from_file(path) for path in files]
    envelope = await batch(PROMPTS, sources=sources, config=config)

    print("\nResult")
    print(f"- Status: {envelope.get('status', 'ok')}")
    print(f"- Answers: {len(envelope.get('answers', []))}")


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

    print("Template recipe")
    print_run_mode(config)
    asyncio.run(main_async(directory, limit=max(1, int(args.limit)), config=config))


if __name__ == "__main__":
    main()
