#!/usr/bin/env python3
"""Recipe: Measure token impact of repeated runs with caching enabled.

Problem:
    You need concrete before/after numbers to justify turning on caching for a
    repeated workload.

Pattern:
    - Keep prompts and inputs fixed.
    - Compare first run (cache warm-up) vs second run (cache reuse).
    - Report token delta and cache metric signal.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from pathlib import Path

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, resolve_dir_or_exit
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
    print_run_mode,
    usage_tokens,
)
from pollux import Config, Source, batch

PROMPTS = [
    "List 5 key findings with one-sentence rationale.",
    "Extract 3 concrete recommendations.",
]


async def main_async(directory: Path, *, limit: int, config: Config) -> None:
    files = sorted(path for path in directory.rglob("*") if path.is_file())[:limit]
    if not files:
        raise SystemExit(f"No files found under: {directory}")

    sources = [Source.from_file(path) for path in files]
    cached_config = replace(config, enable_caching=True)

    warm = await batch(PROMPTS, sources=sources, config=cached_config)
    reuse = await batch(PROMPTS, sources=sources, config=cached_config)

    warm_tokens = usage_tokens(warm)
    reuse_tokens = usage_tokens(reuse)
    saved = (warm_tokens - reuse_tokens) if warm_tokens and reuse_tokens else None

    print("\nCache reuse report")
    print(f"- Warm status: {warm.get('status', 'ok')}")
    print(f"- Reuse status: {reuse.get('status', 'ok')}")
    print(f"- Warm tokens: {warm_tokens if warm_tokens is not None else 'n/a'}")
    print(f"- Reuse tokens: {reuse_tokens if reuse_tokens is not None else 'n/a'}")
    if saved is not None:
        pct = (saved / warm_tokens * 100) if warm_tokens else 0.0
        print(f"- Reported savings: {saved} tokens ({pct:.1f}%)")

    reuse_metrics = reuse.get("metrics")
    cache_used = None
    if isinstance(reuse_metrics, dict):
        cache_used = reuse_metrics.get("cache_used")
    print(f"- cache_used on reuse: {cache_used}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure warm-vs-reuse token behavior with caching enabled.",
    )
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

    print("Context caching baseline")
    print_run_mode(config)
    asyncio.run(main_async(directory, limit=max(1, int(args.limit)), config=config))


if __name__ == "__main__":
    main()
