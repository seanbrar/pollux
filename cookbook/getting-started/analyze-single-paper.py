#!/usr/bin/env python3
"""Recipe: Analyze one source with a clean, inspectable baseline.

Problem:
    You have one document and need a trustworthy first pass before scaling out.

When to use:
    - You are validating prompt quality on a single file.
    - You want a quick read on answer quality and token usage.

When not to use:
    - You need throughput across many files (use multi-source recipes).

Run:
    python -m cookbook getting-started/analyze-single-paper --input path/to/file.pdf

Success check:
    - Status is "ok".
    - Output includes a concise answer excerpt and token count (when provided).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, resolve_file_or_exit
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
from pollux import Config, Source, run

DEFAULT_PROMPT = "Summarize the key ideas and contributions in 5 bullets."


async def main_async(path: Path, prompt: str, *, config: Config) -> None:
    envelope = await run(prompt, source=Source.from_file(path), config=config)

    status = envelope.get("status", "ok")
    answers = envelope.get("answers", [])
    answer = str(answers[0]) if answers else ""

    print_section("Result")
    print_kv_rows(
        [
            ("Status", status),
            ("Source", path),
        ]
    )
    print_excerpt("Answer excerpt", answer, limit=600)
    print_usage(envelope)
    hints = [
        (
            "Next: tighten `--prompt` with explicit output format (bullets/table/JSON)."
            if status == "ok"
            else "Next: resolve non-ok status before scaling this prompt to more sources."
        ),
        (
            "Next: add stronger task constraints to improve answer specificity."
            if len(answer.strip()) < 80
            else "Next: validate factual precision on this baseline before running across more sources."
        ),
    ]
    print_learning_hints(hints)


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
        hint="No input found. Run `just demo-data` or pass --input /path/to/file.",
    )
    config = build_config_or_exit(args)

    print_header("Single-source baseline", config=config)
    asyncio.run(main_async(path, args.prompt, config=config))


if __name__ == "__main__":
    main()
