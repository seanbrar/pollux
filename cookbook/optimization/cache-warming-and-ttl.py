#!/usr/bin/env python3
"""Recipe: Warm cache once, then reuse it with TTL.

Problem:
    Re-running the same analysis wastes latency and tokens when shared context is
    unchanged.

Pattern:
    - Enable caching with a meaningful TTL.
    - Run once to warm.
    - Run again with identical prompts/sources and compare metrics.
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
    "List 5 key concepts with one-sentence explanations.",
    "Extract three actionable recommendations.",
]


def describe(run_name: str, envelope: dict[str, object]) -> None:
    """Print compact run diagnostics."""
    metrics = envelope.get("metrics")
    cache_used = None
    if isinstance(metrics, dict):
        cache_used = metrics.get("cache_used")

    print(
        f"- {run_name}: status={envelope.get('status', 'ok')} "
        f"cache_used={cache_used} tokens={usage_tokens(envelope) or 'n/a'}"
    )


async def main_async(directory: Path, *, limit: int, config: Config, ttl: int) -> None:
    files = sorted(path for path in directory.rglob("*") if path.is_file())[:limit]
    if not files:
        raise SystemExit(f"No files found under: {directory}")

    sources = [Source.from_file(path) for path in files]
    cached_config = replace(config, enable_caching=True, ttl_seconds=max(1, ttl))

    warm = await batch(PROMPTS, sources=sources, config=cached_config)
    reuse = await batch(PROMPTS, sources=sources, config=cached_config)

    print("\nCache comparison")
    describe("warm", warm)
    describe("reuse", reuse)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demonstrate cache warming and TTL-based reuse.",
    )
    parser.add_argument("--input", type=Path, default=None, help="Directory of files")
    parser.add_argument("--limit", type=int, default=2, help="Max files to include")
    parser.add_argument("--ttl", type=int, default=3600, help="Cache TTL in seconds")
    add_runtime_args(parser)
    args = parser.parse_args()

    directory = resolve_dir_or_exit(
        args.input,
        DEFAULT_TEXT_DEMO_DIR,
        hint="No input directory found. Run `make demo-data` or pass --input /path/to/dir.",
    )
    config = build_config_or_exit(args)

    print("Cache warming and TTL")
    print_run_mode(config)
    asyncio.run(
        main_async(
            directory,
            limit=max(1, int(args.limit)),
            config=config,
            ttl=int(args.ttl),
        )
    )


if __name__ == "__main__":
    main()
