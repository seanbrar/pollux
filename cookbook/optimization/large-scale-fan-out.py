#!/usr/bin/env python3
"""Recipe: Fan out many per-file runs with bounded concurrency.

Problem:
    You need throughput across many files while avoiding unbounded in-flight
    requests.

Pattern:
    - Use client-side semaphore for concurrency limits.
    - Keep each unit of work independent.
    - Aggregate status at the end.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

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
from pollux import Config, Source, run

DEFAULT_PROMPT = "Extract three key takeaways."


async def main_async(
    directory: Path,
    *,
    prompt: str,
    limit: int,
    concurrency: int,
    config: Config,
) -> None:
    files = sorted(path for path in directory.rglob("*") if path.is_file())[:limit]
    if not files:
        raise SystemExit(f"No files found under: {directory}")

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run_one(path: Path) -> dict[str, str]:
        async with semaphore:
            envelope = await run(prompt, source=Source.from_file(path), config=config)
            status = str(envelope.get("status", "ok"))
            return {"path": str(path), "status": status}

    results = await asyncio.gather(*(run_one(path) for path in files))
    ok_count = sum(1 for row in results if row["status"] == "ok")
    failures = [row["path"] for row in results if row["status"] != "ok"]

    print_section("Fan-out summary")
    print_kv_rows(
        [
            ("Files", len(files)),
            ("Concurrency", max(1, concurrency)),
            ("ok", f"{ok_count} / {len(results)}"),
        ]
    )
    if failures:
        print_kv_rows([("First failed item", Path(failures[0]).name)])
    print_learning_hints(
        [
            (
                "Next: step concurrency up gradually while reliability remains healthy."
                if not failures
                else "Next: reduce in-flight requests and retry because failures appeared."
            ),
            "Next: tune concurrency with representative file sizes, not only smoke-test inputs.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run independent per-file calls with bounded client-side concurrency.",
    )
    parser.add_argument("--input", type=Path, default=None, help="Directory of files")
    parser.add_argument("--limit", type=int, default=8, help="Max files to include")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max in-flight requests.",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt per file")
    add_runtime_args(parser)
    args = parser.parse_args()

    directory = resolve_dir_or_exit(
        args.input,
        DEFAULT_TEXT_DEMO_DIR,
        hint="No input directory found. Run `just demo-data` or pass --input /path/to/dir.",
    )
    config = build_config_or_exit(args)

    print_header("Large-scale fan-out with bounded concurrency", config=config)
    asyncio.run(
        main_async(
            directory,
            prompt=args.prompt,
            limit=max(1, int(args.limit)),
            concurrency=max(1, int(args.concurrency)),
            config=config,
        )
    )


if __name__ == "__main__":
    main()
