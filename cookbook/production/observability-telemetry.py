#!/usr/bin/env python3
"""🎯 Recipe: Observability Deep Dive with Telemetry and Per-Stage Timings.

When you need to: Understand where time is spent, surface per-stage timings,
and produce metrics that can feed dashboards.

Ingredients:
- Telemetry enabled via environment (best-effort; executor also attaches durations)
- A small batch (multiple prompts/sources) to produce meaningful metrics

What you'll learn:
- Enable and read per-stage durations from the result envelope
- Interpret vectorization/parallel metrics when present
- Sketch how to attach a custom reporter for exports

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


def _pick_files_by_ext(root: Path, exts: list[str], limit: int) -> list[Path]:
    return pick_files_by_ext(root, exts, limit)


async def main_async(directory: Path, limit: int = 2) -> None:
    # Best-effort: set before heavy imports; executor also provides fallback
    os.environ.setdefault("POLLUX_TELEMETRY", "1")

    prompts = [
        "Identify three key takeaways.",
        "List the top entities mentioned.",
    ]
    files = _pick_files_by_ext(directory, [".pdf", ".txt"], limit=limit)
    sources = tuple(types.Source.from_file(p) for p in files)
    if not sources:
        raise SystemExit(f"No files found under {directory}")

    env = await run_batch(prompts, sources, prefer_json=False)
    status = env.get("status", "ok")
    print(f"Status: {status}")

    metrics = env.get("metrics", {})
    _print_durations(metrics)

    # Parallel/vectorization hints (may be absent)
    if isinstance(metrics, dict):
        vec_calls = metrics.get("vectorized_n_calls")
        par_calls = metrics.get("parallel_n_calls")
        if vec_calls is not None:
            print(f"\n🔗 Vectorized API calls: {vec_calls}")
        if par_calls is not None:
            print(f"\n🧵 Parallel fan-out calls: {par_calls}")

    # Sketch: attach a custom reporter (see examples/ for a Prometheus demo)
    print(
        "\n💡 Tip: For exports, implement TelemetryReporter and pass into TelemetryContext()."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Observability telemetry demo")
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
