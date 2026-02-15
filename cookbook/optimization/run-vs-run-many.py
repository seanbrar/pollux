#!/usr/bin/env python3
"""Recipe: Compare `run()` loops vs a single `run_many()` call for the same prompt set.

Problem:
    You have multiple questions about the same source and want a simple, efficient
    way to run them.

Key idea:
    `run_many()` vectorizes prompts: you provide a list of prompts and shared
    sources once, and Pollux executes the plan (including concurrency and shared
    uploads) for you.

When to use:
    - You want multiple answers about the same source.
    - You want a clean baseline before building custom orchestration.

When not to use:
    - You need per-file processing across many files (use map/fan-out recipes).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import time
from typing import TYPE_CHECKING, cast

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, resolve_file_or_exit
from cookbook.utils.presentation import (
    print_excerpt,
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
    print_usage,
)
from cookbook.utils.runtime import add_runtime_args, build_config_or_exit, usage_tokens
from pollux import Config, Source, run, run_many

if TYPE_CHECKING:
    from pollux.result import ResultEnvelope

PROMPTS = [
    "Summarize the key ideas in 3 bullets.",
    "Extract 3 concrete action items.",
    "List 5 named entities and their roles.",
]


async def run_loop(
    prompts: list[str], *, source: Source, config: Config
) -> dict[str, object]:
    start = time.perf_counter()
    results = []
    token_sum = 0
    for p in prompts:
        env = await run(p, source=source, config=config)
        results.append(env)
        token_sum += int(usage_tokens(env) or 0)
    elapsed = time.perf_counter() - start
    return {
        "elapsed_s": elapsed,
        "token_sum": token_sum if token_sum > 0 else None,
        "results": results,
    }


async def run_batched(
    prompts: list[str], *, source: Source, config: Config
) -> dict[str, object]:
    start = time.perf_counter()
    env = await run_many(prompts, sources=[source], config=config)
    elapsed = time.perf_counter() - start
    tokens = usage_tokens(env)
    return {
        "elapsed_s": elapsed,
        "tokens": tokens,
        "result": env,
    }


async def main_async(path: Path, *, config: Config) -> None:
    source = Source.from_file(path)

    print_section("Workload")
    print_kv_rows([("Source", path), ("Prompts", len(PROMPTS))])

    loop = await run_loop(PROMPTS, source=source, config=config)
    batched = await run_batched(PROMPTS, source=source, config=config)

    loop_elapsed_raw = loop.get("elapsed_s")
    batched_elapsed_raw = batched.get("elapsed_s")
    loop_elapsed = (
        float(loop_elapsed_raw) if isinstance(loop_elapsed_raw, (int, float)) else 0.0
    )
    batched_elapsed = (
        float(batched_elapsed_raw)
        if isinstance(batched_elapsed_raw, (int, float))
        else 0.0
    )
    speedup = (loop_elapsed / batched_elapsed) if batched_elapsed > 0 else None

    print_section("Comparison")
    print_kv_rows(
        [
            ("Loop `run()` wall time (s)", f"{loop_elapsed:.2f}"),
            ("Batched `run_many()` wall time (s)", f"{batched_elapsed:.2f}"),
            ("Speedup (loop / batched)", f"{speedup:.2f}x" if speedup else "n/a"),
            (
                "Loop tokens (sum)",
                loop["token_sum"] if loop["token_sum"] is not None else "n/a",
            ),
            (
                "Batched tokens",
                batched["tokens"] if batched["tokens"] is not None else "n/a",
            ),
        ]
    )

    result_obj = batched.get("result")
    if isinstance(result_obj, dict):
        result = result_obj  # runtime TypedDict is a dict
        answers = [str(a) for a in result.get("answers", [])]
        if answers:
            print_excerpt("Batched first answer excerpt", answers[0], limit=320)
        print_usage(cast("ResultEnvelope", result_obj))

    print_learning_hints(
        [
            "Next: prefer `run_many()` when prompts share the same source(s).",
            (
                "Next: rerun in `--no-mock` to see real benefits from shared uploads/provider overhead."
                if config.use_mock
                else "Next: scale prompt sets incrementally and watch duration/tokens."
            ),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare looped run() vs batched run_many() for one source.",
    )
    parser.add_argument(
        "--input", type=Path, default=None, help="Path to a source file"
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    path = resolve_file_or_exit(
        args.input,
        search_dir=DEFAULT_TEXT_DEMO_DIR,
        exts=[".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg"],
        hint="No input found. Run `make demo-data` or pass --input /path/to/file.",
    )
    config = build_config_or_exit(args)

    print_header("Prompt batching: run vs run_many", config=config)
    asyncio.run(main_async(path, config=config))


if __name__ == "__main__":
    main()
