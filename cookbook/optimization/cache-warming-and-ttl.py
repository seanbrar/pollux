#!/usr/bin/env python3
"""Recipe: Measure cache impact and pick a sane TTL.

Problem:
    Re-running the same workload can waste latency and tokens when the shared
    context is unchanged.

Pattern:
    - Keep prompts and sources fixed.
    - Prepare an environment with a ``CachePolicy`` to create a persistent cache.
    - Run once to warm and once to reuse (back-to-back) over that environment.
    - Compare tokens and the cache signal.

Persistent caching is a provider capability (e.g. Gemini). Run with ``--mock``
for an offline smoke test, or ``--provider gemini`` against a real key.
"""

from __future__ import annotations

import argparse
import asyncio
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
from pollux import CachePolicy, Config, Source, prepare_environment, run_many

if TYPE_CHECKING:
    from pollux import OutputCollection

PROMPTS = (
    "List 5 key concepts with one-sentence explanations.",
    "Extract three actionable recommendations.",
)


def describe(run_name: str, collection: OutputCollection) -> None:
    """Print compact run diagnostics."""
    cache_used = (
        collection.outputs[0].metrics.cache_used if collection.outputs else None
    )
    print(
        f"- {run_name}: status={collection.status} "
        f"cache_used={cache_used} tokens={usage_tokens(collection) or 'n/a'}"
    )


async def main_async(directory: Path, *, limit: int, config: Config, ttl: int) -> None:
    files = sorted(path for path in directory.rglob("*") if path.is_file())[:limit]
    if not files:
        raise SystemExit(f"No files found under: {directory}")

    sources = [Source.from_file(path) for path in files]

    environment = await prepare_environment(
        sources=sources,
        cache=CachePolicy(ttl_seconds=ttl),
        config=config,
    )

    warm = await run_many(PROMPTS, environment=environment, config=config)
    reuse = await run_many(PROMPTS, environment=environment, config=config)
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
        hint="No input directory found. Run `just demo-data` or pass --input /path/to/dir.",
    )
    config = build_config_or_exit(args)

    print_header("Cache warming and TTL", config=config)
    asyncio.run(
        main_async(
            directory,
            limit=max(1, int(args.limit)),
            config=config,
            ttl=max(1, int(args.ttl)),
        )
    )


if __name__ == "__main__":
    main()
