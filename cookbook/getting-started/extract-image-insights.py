#!/usr/bin/env python3
"""Recipe: Extract fast highlights from one image.

Problem:
    You need a quick, inspectable baseline for image prompts before scaling to
    larger multimodal workflows.

When to use:
    - You are iterating on image prompt wording.
    - You need a small set of reliable, repeatable image outputs.

When not to use:
    - You need multi-image aggregation (build a directory processor or fan-out).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from cookbook.utils.demo_inputs import DEFAULT_MEDIA_DEMO_DIR, resolve_file_or_exit
from cookbook.utils.presentation import (
    print_excerpt,
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
    print_usage,
)
from cookbook.utils.runtime import add_runtime_args, build_config_or_exit
from pollux import Config, Source, run_many

PROMPTS = [
    "Describe the image in 3 bullets (be concrete).",
    "List visible objects/entities and their attributes (color, size, location).",
    "If there is any text, extract it verbatim. Otherwise say 'no text'.",
]


async def main_async(path: Path, *, config: Config) -> None:
    envelope = await run_many(PROMPTS, sources=[Source.from_file(path)], config=config)
    answers = [str(a) for a in envelope.get("answers", [])]

    print_section("Image result")
    print_kv_rows(
        [
            ("Status", envelope.get("status", "ok")),
            ("Image", path),
            ("Prompts", len(PROMPTS)),
        ]
    )
    for idx, answer in enumerate(answers, start=1):
        print_excerpt(f"Prompt {idx} excerpt", answer, limit=260)
    print_usage(envelope)
    print_learning_hints(
        [
            "Next: tighten prompts to demand evidence (e.g., bounding-box style references) if outputs are vague.",
            "Next: once prompts are stable, scale with Broadcast Process Files or Large-Scale Fan-Out.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract highlights and entities from one image source.",
    )
    parser.add_argument("--input", type=Path, default=None, help="Path to image file")
    add_runtime_args(parser)
    args = parser.parse_args()

    path = resolve_file_or_exit(
        args.input,
        search_dir=DEFAULT_MEDIA_DEMO_DIR,
        exts=[".png", ".jpg", ".jpeg"],
        hint="No image found. Run `make demo-data` or pass --input /path/to/image.",
    )
    config = build_config_or_exit(args)

    print_header("Single-image insight extraction", config=config)
    asyncio.run(main_async(path, config=config))


if __name__ == "__main__":
    main()

