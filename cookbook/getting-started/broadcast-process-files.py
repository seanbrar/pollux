#!/usr/bin/env python3
"""Recipe: Process a directory by broadcasting the same prompts per file.

Problem:
    You need consistent answers across many files with minimal orchestration.

Key idea:
    Pollux vectorizes *prompts* (via run_many), not *files*. This recipe loops over
    files and, for each file, uses one run_many call to ask multiple questions.

When to use:
    - You want a simple, grokkable "map over files" baseline.
    - You want multi-question output per file without designing a full pipeline.

When not to use:
    - You need high throughput (use fan-out/concurrency recipes).
    - You need durable resume/retry guarantees (use production recipes).

Run:
    python -m cookbook getting-started/broadcast-process-files -- --input ./docs --limit 4
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import time

from cookbook.utils.demo_inputs import (
    DEFAULT_TEXT_DEMO_DIR,
    pick_files_by_ext,
    resolve_dir_or_exit,
)
from cookbook.utils.presentation import (
    print_excerpt,
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
)
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
    usage_tokens,
)
from pollux import Config, Source, run_many

DEFAULT_PROMPTS = [
    "List 3 key takeaways.",
    "Extract the main entities and roles.",
]

SUPPORTED_EXTS = [".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg"]


async def main_async(
    directory: Path,
    *,
    limit: int,
    prompts: list[str],
    config: Config,
) -> None:
    files = pick_files_by_ext(directory, SUPPORTED_EXTS, limit=max(1, limit))
    if not files:
        raise SystemExit(f"No supported files found under: {directory}")

    start = time.perf_counter()
    total_tokens = 0
    status_counts: dict[str, int] = {"ok": 0, "partial": 0, "error": 0}

    print_section("Per-file results")
    for idx, path in enumerate(files, start=1):
        envelope = await run_many(prompts, sources=[Source.from_file(path)], config=config)
        status = str(envelope.get("status", "ok"))
        status_counts[status] = status_counts.get(status, 0) + 1
        total_tokens += int(usage_tokens(envelope) or 0)

        answers = [str(answer) for answer in envelope.get("answers", [])]
        print_kv_rows(
            [
                ("File", f"[{idx}/{len(files)}] {path.name}"),
                ("Status", status),
                ("Answers", f"{len(answers)} / {len(prompts)}"),
            ]
        )
        if answers:
            # Keep output compact: show the first prompt excerpt per file by default.
            print_excerpt("First prompt excerpt", answers[0], limit=240)

    duration_s = time.perf_counter() - start
    print_section("Summary")
    print_kv_rows(
        [
            ("Files", len(files)),
            ("Prompts per file", len(prompts)),
            ("Statuses", " ".join(f"{k}={v}" for k, v in status_counts.items())),
            ("Total tokens (sum)", total_tokens if total_tokens > 0 else "n/a"),
            ("Wall time (s)", f"{duration_s:.2f}"),
        ]
    )
    print_learning_hints(
        [
            "Next: keep prompts stable and iterate until per-file excerpts look consistently specific.",
            "Next: scale with bounded concurrency (see Large-Scale Fan-Out) once this baseline is solid.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process a directory by running the same prompts per file.",
    )
    parser.add_argument("--input", type=Path, default=None, help="Directory of files")
    parser.add_argument("--limit", type=int, default=3, help="Max files to include")
    parser.add_argument(
        "--prompt",
        action="append",
        dest="prompts",
        default=[],
        help=(
            "Prompt to run (repeat flag for multiple prompts). "
            "Defaults to two baseline prompts."
        ),
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    directory = resolve_dir_or_exit(
        args.input,
        DEFAULT_TEXT_DEMO_DIR,
        hint="No input directory found. Run `make demo-data` or pass --input /path/to/dir.",
    )
    prompts = args.prompts or DEFAULT_PROMPTS
    config = build_config_or_exit(args)

    print_header("Directory processing baseline", config=config)
    asyncio.run(
        main_async(
            directory,
            limit=max(1, int(args.limit)),
            prompts=prompts,
            config=config,
        )
    )


if __name__ == "__main__":
    main()
