#!/usr/bin/env python3
"""🎯 Recipe: Custom Integrations via Telemetry Reporter

When you need to: Export timings/metrics to your system by attaching a custom
reporter (e.g., to logs, CSV, Prometheus, or a monitoring service).

Ingredients:
- Implement `TelemetryReporter` protocol methods
- Use `TelemetryContext` to enable and capture timings/metrics

What you'll learn:
- Write a minimal reporter
- Attach it and run a batch
- Inspect the collected data

Difficulty: ⭐⭐⭐
Time: ~8-12 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from cookbook.utils.demo_inputs import (
    DEFAULT_TEXT_DEMO_DIR,
    pick_files_by_ext,
)
from pollux import types
from pollux.frontdoor import run_batch
from pollux.telemetry import TelemetryContext


class PrintReporter:
    def record_timing(self, scope: str, duration: float, **metadata: Any) -> None:
        print(f"TIMING {scope:<35} {duration:.4f}s depth={metadata.get('depth')}")

    def record_metric(self, scope: str, value: Any, **metadata: Any) -> None:
        print(f"METRIC {scope:<35} {value} parent={metadata.get('parent_scope')}")


async def main_async(directory: Path, limit: int = 2) -> None:
    prompts = ["List 3 key takeaways."]
    files = pick_files_by_ext(directory, [".pdf", ".txt"], limit=limit)
    sources = tuple(types.Source.from_file(p) for p in files)
    if not sources:
        raise SystemExit(f"No files found under {directory}")

    # Enable telemetry with our custom reporter for this scope
    ctx = TelemetryContext(PrintReporter())
    with ctx("cookbook.custom_integrations.run"):
        env = await run_batch(prompts, sources)
        print(f"Status: {env.get('status', 'ok')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Custom telemetry integration demo")
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
