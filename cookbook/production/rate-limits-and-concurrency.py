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
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from pollux.result import ResultEnvelope

PROMPTS = [
    "Identify 3 key facts.",
    "List main entities.",
    "Summarize in 3 bullets.",
]


def duration_s(envelope: ResultEnvelope) -> object:
    """Extract duration metric when available."""
    metrics = envelope.get("metrics")
    if isinstance(metrics, dict):
        return metrics.get("duration_s", "n/a")
    return "n/a"


def as_float(value: object) -> float | None:
    """Return float value when conversion is safe."""
    if isinstance(value, (int, float)):
        return float(value)
    return None


async def main_async(
    directory: Path, *, limit: int, config: Config, concurrency: int
) -> None:
    files = sorted(path for path in directory.rglob("*") if path.is_file())[:limit]
    if not files:
        raise SystemExit(f"No files found under: {directory}")

    sources = [Source.from_file(path) for path in files]
    config_seq = replace(config, request_concurrency=1)
    config_par = replace(config, request_concurrency=max(1, concurrency))

    sequential = await run_many(PROMPTS, sources=sources, config=config_seq)
    parallel = await run_many(PROMPTS, sources=sources, config=config_par)
    seq_d = as_float(duration_s(sequential))
    par_d = as_float(duration_s(parallel))
    speedup = None
    if seq_d is not None and par_d is not None and par_d > 0:
        speedup = seq_d / par_d

    print_section("Concurrency comparison")
    print_kv_rows(
        [
            (
                "sequential(c=1)",
                f"status={sequential.get('status', 'ok')} duration_s={duration_s(sequential)}",
            ),
            (
                f"bounded(c={max(1, concurrency)})",
                f"status={parallel.get('status', 'ok')} duration_s={duration_s(parallel)}",
            ),
        ]
    )
    if speedup is not None:
        print_kv_rows([("Speedup", f"{speedup:.2f}x")])
    print_learning_hints(
        [
            (
                "Next: keep bounded concurrency as your default candidate because it is faster and stable."
                if speedup is not None and speedup > 1.0
                else "Next: repeat runs or lower concurrency because no clear speedup was observed."
            ),
            "Next: finalize production concurrency using median duration from multiple runs.",
        ]
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

    print_header("Rate limits and concurrency tuning", config=config)
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
