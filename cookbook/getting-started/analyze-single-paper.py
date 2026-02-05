#!/usr/bin/env python3
"""Recipe: Analyze one source with a clean, inspectable baseline.

Problem:
    You have one document and need a trustworthy first pass before scaling out.

When to use:
    - You are validating prompt quality on a single file.
    - You want a quick read on answer quality and token usage.

When not to use:
    - You need throughput across many files (use batch recipes).

Run:
    python -m cookbook getting-started/analyze-single-paper -- --input path/to/file.pdf

Success check:
    - Status is "ok".
    - Output includes a concise answer excerpt and token count (when provided).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, resolve_file_or_exit
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
    print_run_mode,
    usage_tokens,
)
from pollux import Config, Source, run

DEFAULT_PROMPT = "Summarize the key ideas and contributions in 5 bullets."


async def main_async(path: Path, prompt: str, *, config: Config) -> None:
    envelope = await run(prompt, source=Source.from_file(path), config=config)

    status = envelope.get("status", "ok")
    answers = envelope.get("answers", [])
    answer = str(answers[0]) if answers else ""
    excerpt = answer[:600] + ("..." if len(answer) > 600 else "")

    print("\nResult")
    print(f"- Status: {status}")
    print(f"- Source: {path}")

    if excerpt:
        print("\nAnswer excerpt")
        print(excerpt)

    tokens = usage_tokens(envelope)
    if tokens is not None:
        print(f"\nUsage\n- Total tokens: {tokens}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze one source and inspect the first answer.",
    )
    parser.add_argument(
        "--input", type=Path, default=None, help="Path to a source file"
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Question/instruction to run against the source.",
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

    print("Single-source baseline")
    print_run_mode(config)
    asyncio.run(main_async(path, args.prompt, config=config))


if __name__ == "__main__":
    main()
