#!/usr/bin/env python3
"""Recipe: Measure cache impact and pick a sane TTL.

Problem:
    Re-running the same workload can waste latency and tokens when the shared
    context is unchanged.

Pattern:
    - Keep prompts and sources fixed.
    - Enable caching with a meaningful TTL.
    - Run once to warm and once to reuse (back-to-back).
    - Compare tokens and cache signal.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, resolve_dir_or_exit
from cookbook.utils.presentation import (
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
)
from cookbook.utils.runtime import add_runtime_args, build_config_or_exit, usage_tokens
from pollux import Config, Source, run_many

if TYPE_CHECKING:
    from pollux.result import ResultEnvelope

PROMPTS = [
    "List 5 key concepts with one-sentence explanations.",
    "Extract three actionable recommendations.",
]


def describe(run_name: str, envelope: ResultEnvelope) -> None:
    """Print compact run diagnostics."""
    metrics = envelope.get("metrics")
    cache_used = None
    if isinstance(metrics, dict):
        cache_used = metrics.get("cache_used")

    print(
        f"- {run_name}: status={envelope.get('status', 'ok')} "
        f"cache_used={cache_used} tokens={usage_tokens(envelope) or 'n/a'}"
    )


async def main_async(
    directory: Path, *, limit: int, config: Config, ttl: int
) -> None:
    files = sorted(path for path in directory.rglob("*") if path.is_file())[:limit]
    if not files:
        raise SystemExit(f"No files found under: {directory}")

    sources = [Source.from_file(path) for path in files]
    cached_config = replace(config, enable_caching=True, ttl_seconds=max(1, ttl))

    warm = await run_many(PROMPTS, sources=sources, config=cached_config)
    reuse = await run_many(PROMPTS, sources=sources, config=cached_config)
    warm_tokens = usage_tokens(warm)
    reuse_tokens = usage_tokens(reuse)
    saved = None
    if isinstance(warm_tokens, int) and isinstance(reuse_tokens, int):
        saved = warm_tokens - reuse_tokens

    print_section("Cache impact report")
    describe("warm", warm)
    describe("reuse", reuse)
    if saved is not None:
        warm_total = warm_tokens if isinstance(warm_tokens, int) else 0
        pct = (saved / warm_total * 100) if warm_total > 0 else 0.0
        print_kv_rows(
            [
                ("Token delta (warm - reuse)", saved),
                ("Reported savings", f"{pct:.1f}%"),
            ]
        )
    print_learning_hints(
        [
            (
                "Next: keep caching enabled for this workload because reuse is cheaper."
                if isinstance(saved, int) and saved > 0
                else "Next: retry with larger repeated context because savings are currently small."
            ),
            "Next: keep prompts and sources fixed for clean cache-impact comparisons.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure warm-vs-reuse behavior with caching enabled and a chosen TTL.",
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
    cached_config = replace(
        config, enable_caching=True, ttl_seconds=max(1, int(args.ttl))
    )

    print_header("Cache warming and TTL", config=cached_config)
    asyncio.run(
        main_async(
            directory,
            limit=max(1, int(args.limit)),
            config=cached_config,
            ttl=int(args.ttl),
        )
    )


if __name__ == "__main__":
    main()
