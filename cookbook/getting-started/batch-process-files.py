#!/usr/bin/env python3
"""Recipe: Batch process a directory of files with shared prompts.

Problem:
    You need consistent answers across many files without writing orchestration code.

When to use:
    - You have one directory and a fixed question set.
    - You want a first throughput baseline before adding production controls.

When not to use:
    - You need resume/retry guarantees (use production recipes).

Run:
    python -m cookbook getting-started/batch-process-files -- --input ./docs --limit 4
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, resolve_dir_or_exit
from cookbook.utils.presentation import (
    print_excerpt,
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
    print_usage,
)
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
)
from pollux import Config, Source, batch

DEFAULT_PROMPTS = [
    "List 3 key takeaways.",
    "Extract the main entities and roles.",
]


async def main_async(
    directory: Path,
    *,
    limit: int,
    prompts: list[str],
    config: Config,
) -> None:
    files = sorted(path for path in directory.rglob("*") if path.is_file())[:limit]
    if not files:
        raise SystemExit(f"No files found under: {directory}")

    sources = [Source.from_file(path) for path in files]
    envelope = await batch(prompts, sources=sources, config=config)

    answers = [str(answer) for answer in envelope.get("answers", [])]
    print_section("Batch result")
    print_kv_rows(
        [
            ("Status", envelope.get("status", "ok")),
            ("Files processed", len(files)),
            ("Prompts", len(prompts)),
        ]
    )

    for index, answer in enumerate(answers, start=1):
        print_excerpt(f"Answer {index}", answer, limit=280)

    metrics = envelope.get("metrics")
    if isinstance(metrics, dict) and "duration_s" in metrics:
        print_section("Metrics")
        print_kv_rows([("Duration (s)", metrics["duration_s"])])
    print_usage(envelope)
    print_learning_hints(
        [
            (
                "Next: tune prompt quality now that answer coverage matches prompt count."
                if len(answers) == len(prompts)
                else "Next: inspect prompt/source compatibility because answer coverage is incomplete."
            ),
            "Next: raise `--limit` gradually and watch duration/tokens before switching to real API mode.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run shared prompts over multiple files in one batch call.",
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

    print_header("Directory batch baseline", config=config)
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
