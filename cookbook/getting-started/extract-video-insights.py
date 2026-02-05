#!/usr/bin/env python3
"""Recipe: Extract structured insights from one video.

Problem:
    You need fast highlights from a single video before scaling to multi-video
    research workflows.

When to use:
    - You are validating prompts for one MP4/MOV input.
    - You need concise highlights and entity extraction.

When not to use:
    - You need cross-video synthesis (use multi-video recipe).

Run:
    python -m cookbook getting-started/extract-video-insights -- --input ./clip.mp4
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from cookbook.utils.demo_inputs import DEFAULT_MEDIA_DEMO_DIR, resolve_file_or_exit
from cookbook.utils.retry import retry_async
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
    print_run_mode,
    usage_tokens,
)
from pollux import Config, Source, batch

DEFAULT_PROMPTS = [
    "List 3 key moments with timestamps when visible.",
    "Identify the main entities or objects and their role in the scene.",
]


async def main_async(path: Path, *, config: Config) -> None:
    source = Source.from_file(path)
    envelope = await retry_async(
        lambda: batch(DEFAULT_PROMPTS, sources=[source], config=config),
        retries=3,
        initial_delay=1.0,
        backoff=1.8,
    )

    answers = [str(answer) for answer in envelope.get("answers", [])]
    print("\nVideo result")
    print(f"- Status: {envelope.get('status', 'ok')}")
    print(f"- Video: {path}")

    for index, answer in enumerate(answers, start=1):
        excerpt = answer[:320] + ("..." if len(answer) > 320 else "")
        print(f"\nPrompt {index} excerpt\n{excerpt}")

    tokens = usage_tokens(envelope)
    if tokens is not None:
        print(f"\nUsage\n- Total tokens: {tokens}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract highlights and entities from one video source.",
    )
    parser.add_argument("--input", type=Path, default=None, help="Path to MP4/MOV file")
    add_runtime_args(parser)
    args = parser.parse_args()

    path = resolve_file_or_exit(
        args.input,
        search_dir=DEFAULT_MEDIA_DEMO_DIR,
        exts=[".mp4", ".mov"],
        hint="No video found. Run `make demo-data` or pass --input /path/to/video.",
    )
    config = build_config_or_exit(args)

    print("Single-video insight extraction")
    print_run_mode(config)
    asyncio.run(main_async(path, config=config))


if __name__ == "__main__":
    main()
