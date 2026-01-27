#!/usr/bin/env python3
"""🎯 Recipe: Monitoring and Telemetry (Per-Stage Timings)

When you need to: Enable telemetry, inspect stage timings, and surface metrics
to plug into dashboards.

Ingredients:
- `POLLUX_TELEMETRY=1` (recommended) or rely on envelope metrics
- A small batch (multiple prompts and at least one file)

What you'll learn:
- Enable telemetry via env and read per-stage durations
- Understand vectorization and parallel metrics
- Print a human-readable report

Difficulty: ⭐⭐⭐
Time: ~8-10 minutes
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import Any

from cookbook.utils.demo_inputs import (
    DEFAULT_TEXT_DEMO_DIR,
    pick_files_by_ext,
)
from pollux import types
from pollux.frontdoor import run_batch


def _print_durations(metrics: dict[str, Any]) -> None:
    durs = metrics.get("durations", {}) if isinstance(metrics, dict) else {}
    if not isinstance(durs, dict) or not durs:
        print("No stage durations available.")
        return
    print("\n⏱️  Stage durations (s):")
    for k, v in durs.items():
        try:
            print(f"  {k:<28} {float(v):.4f}")
        except Exception:
            continue


async def main_async(directory: Path, limit: int = 2) -> None:
    os.environ.setdefault("POLLUX_TELEMETRY", "1")
    prompts = ["Identify three key takeaways.", "List top entities mentioned."]
    files = pick_files_by_ext(directory, [".pdf", ".txt"], limit=limit)
    sources = tuple(types.Source.from_file(p) for p in files)
    if not sources:
        raise SystemExit(f"No files found under {directory}")
    env = await run_batch(prompts, sources, prefer_json=False)
    print(f"Status: {env.get('status', 'ok')}")
    metrics = env.get("metrics", {})
    _print_durations(metrics)
    if isinstance(metrics, dict):
        if metrics.get("vectorized_n_calls") is not None:
            print(f"\n🔗 Vectorized API calls: {metrics.get('vectorized_n_calls')}")
        if metrics.get("parallel_n_calls") is not None:
            print(f"🧵 Parallel fan-out calls: {metrics.get('parallel_n_calls')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitoring and telemetry demo")
    parser.add_argument("--input", type=Path, default=None, help="Directory with files")
    parser.add_argument("--limit", type=int, default=2, help="Max files to read")
    args = parser.parse_args()
    directory = args.input or DEFAULT_TEXT_DEMO_DIR
    if not directory.exists():
        raise SystemExit("No input provided. Run `make demo-data` or pass --input.")
    print("Note: File size/count affect runtime and tokens.")
    asyncio.run(main_async(directory, max(1, int(args.limit))))


if __name__ == "__main__":
    main()
