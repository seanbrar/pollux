#!/usr/bin/env python3
"""Recipe: Compare sequential vs bounded-concurrency execution settings.

Problem:
    You need to tune request concurrency while respecting provider rate limits.

Pattern:
    - Run the same workload with concurrency=1 and concurrency=N.
    - Compare status and duration metrics.
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
)
from pollux import Config, Source, batch

PROMPTS = [
    "Identify 3 key facts.",
    "List main entities.",
    "Summarize in 3 bullets.",
]


def duration_s(envelope: dict[str, object]) -> object:
    """Extract duration metric when available."""
    metrics = envelope.get("metrics")
    if isinstance(metrics, dict):
        return metrics.get("duration_s", "n/a")
    return "n/a"


async def main_async(
    directory: Path, *, limit: int, config: Config, concurrency: int
) -> None:
    files = sorted(path for path in directory.rglob("*") if path.is_file())[:limit]
    if not files:
        raise SystemExit(f"No files found under: {directory}")

    sources = [Source.from_file(path) for path in files]
    config_seq = replace(config, request_concurrency=1)
    config_par = replace(config, request_concurrency=max(1, concurrency))

    sequential = await batch(PROMPTS, sources=sources, config=config_seq)
    parallel = await batch(PROMPTS, sources=sources, config=config_par)

    print("\nConcurrency comparison")
    print(
        f"- sequential(c=1): status={sequential.get('status', 'ok')} "
        f"duration_s={duration_s(sequential)}"
    )
    print(
        f"- bounded(c={max(1, concurrency)}): status={parallel.get('status', 'ok')} "
        f"duration_s={duration_s(parallel)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare request_concurrency settings on the same workload.",
    )
    parser.add_argument("--input", type=Path, default=None, help="Directory of files")
    parser.add_argument("--limit", type=int, default=3, help="Max files to include")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Bounded concurrency for comparison run.",
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    directory = resolve_dir_or_exit(
        args.input,
        DEFAULT_TEXT_DEMO_DIR,
        hint="No input directory found. Run `make demo-data` or pass --input /path/to/dir.",
    )
    config = build_config_or_exit(args)

    print("Rate limits and concurrency tuning")
    print_run_mode(config)
    asyncio.run(
        main_async(
            directory,
            limit=max(1, int(args.limit)),
            config=config,
            concurrency=max(1, int(args.concurrency)),
        )
    )


if __name__ == "__main__":
    main()
