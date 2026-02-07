#!/usr/bin/env python3
"""Recipe: Tune `request_concurrency` safely against rate limits.

Problem:
    You need to increase throughput without triggering rate limits or unstable
    error rates.

Key idea:
    Pollux concurrency applies to *calls* inside a single plan (usually one call
    per prompt). This recipe holds the inputs and prompt count constant, then
    compares:
    - sequential (c=1) vs bounded concurrency (c=N)
    - across multiple trials (because latency is noisy)

When to use:
    - You have a prompt set that is stable enough to benchmark.
    - You need to choose a safe default concurrency for production.

When not to use:
    - You need concurrency across *files/items* (use Large-Scale Fan-Out).
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import statistics
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, pick_files_by_ext, resolve_dir_or_exit
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

SUPPORTED_EXTS = [".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg"]


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


def build_prompts(count: int) -> list[str]:
    """Build a stable prompt set of length `count`.

    Prompts are intentionally similar in shape so the benchmark reflects request
    overhead and concurrency behavior rather than prompt creativity.
    """
    base = [
        "Extract one concrete claim from the sources and quote it verbatim. prompt_id={i}",
        "List 2 named entities from the sources with roles. prompt_id={i}",
        "Summarize the sources in 1 bullet. prompt_id={i}",
    ]
    prompts: list[str] = []
    for i in range(max(1, int(count))):
        template = base[i % len(base)]
        prompts.append(template.format(i=i + 1))
    return prompts


async def run_trial(
    *,
    prompts: list[str],
    sources: list[Source],
    config: Config,
) -> dict[str, Any]:
    """Run one trial and return a compact outcome dict."""
    try:
        env = await run_many(prompts, sources=sources, config=config)
    except Exception as exc:
        return {"ok": False, "status": "error", "duration_s": None, "error": str(exc)}

    d = as_float(duration_s(env))
    metrics = env.get("metrics")
    n_calls = None
    if isinstance(metrics, dict):
        n_calls = metrics.get("n_calls")
    return {
        "ok": env.get("status", "ok") == "ok",
        "status": env.get("status", "ok"),
        "duration_s": d,
        "n_calls": n_calls,
    }


async def main_async(
    directory: Path,
    *,
    limit: int,
    config: Config,
    concurrency: int,
    prompts_count: int,
    trials: int,
) -> None:
    files = pick_files_by_ext(directory, SUPPORTED_EXTS, limit=max(1, limit))
    if not files:
        raise SystemExit(f"No supported files found under: {directory}")

    sources = [Source.from_file(path) for path in files]
    config_seq = replace(config, request_concurrency=1)
    config_par = replace(config, request_concurrency=max(1, concurrency))

    prompts = build_prompts(prompts_count)
    n_trials = max(1, int(trials))

    print_section("Workload")
    print_kv_rows(
        [
            ("Context sources", len(files)),
            ("Prompts", len(prompts)),
            ("Trials", n_trials),
        ]
    )

    seq_durations: list[float] = []
    par_durations: list[float] = []
    seq_ok = 0
    par_ok = 0

    print_section("Trials")
    for i in range(1, n_trials + 1):
        seq = await run_trial(prompts=prompts, sources=sources, config=config_seq)
        par = await run_trial(prompts=prompts, sources=sources, config=config_par)

        seq_ok += 1 if seq.get("ok") else 0
        par_ok += 1 if par.get("ok") else 0

        seq_d = seq.get("duration_s")
        par_d = par.get("duration_s")
        if isinstance(seq_d, float):
            seq_durations.append(seq_d)
        if isinstance(par_d, float):
            par_durations.append(par_d)

        print_kv_rows(
            [
                (
                    f"trial {i} sequential(c=1)",
                    f"status={seq.get('status')} duration_s={seq_d if seq_d is not None else 'n/a'}",
                ),
                (
                    f"trial {i} bounded(c={max(1, concurrency)})",
                    f"status={par.get('status')} duration_s={par_d if par_d is not None else 'n/a'}",
                ),
            ]
        )

    seq_median = statistics.median(seq_durations) if seq_durations else None
    par_median = statistics.median(par_durations) if par_durations else None
    speedup = (
        (seq_median / par_median)
        if isinstance(seq_median, float) and isinstance(par_median, float) and par_median > 0
        else None
    )

    print_section("Summary")
    print_kv_rows(
        [
            ("sequential ok rate", f"{seq_ok} / {n_trials}"),
            ("bounded ok rate", f"{par_ok} / {n_trials}"),
            ("sequential median duration (s)", f"{seq_median:.2f}" if isinstance(seq_median, float) else "n/a"),
            ("bounded median duration (s)", f"{par_median:.2f}" if isinstance(par_median, float) else "n/a"),
            ("median speedup", f"{speedup:.2f}x" if speedup is not None else "n/a"),
        ]
    )
    print_learning_hints(
        [
            (
                "Next: keep bounded concurrency as your default candidate because it is faster and stable."
                if speedup is not None and speedup > 1.1 and par_ok == n_trials
                else "Next: lower concurrency or increase trials because results are noisy or unstable."
            ),
            "Next: tune item-level concurrency separately using Large-Scale Fan-Out (this recipe is per-plan concurrency).",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tune request_concurrency and observe rate-limit stability across trials.",
    )
    parser.add_argument("--input", type=Path, default=None, help="Directory of files")
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help=(
            "Number of context files to include (default: 1). "
            "Keep this fixed while tuning concurrency."
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Bounded concurrency for comparison run.",
    )
    parser.add_argument(
        "--prompts",
        type=int,
        default=12,
        help="Number of prompts to run per trial (default: 12).",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=3,
        help="Number of repeated comparisons to run (default: 3).",
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
            prompts_count=max(1, int(args.prompts)),
            trials=max(1, int(args.trials)),
        )
    )


if __name__ == "__main__":
    main()
