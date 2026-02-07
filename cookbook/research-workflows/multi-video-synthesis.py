#!/usr/bin/env python3
"""Recipe: Compare themes across multiple video sources.

Problem:
    You need one synthesis across several videos (local files and/or URLs).

Pattern:
    - Build a mixed source list.
    - Ask vectorized prompts once.
    - Review consolidated themes and disagreements.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from cookbook.utils.demo_inputs import DEFAULT_MEDIA_DEMO_DIR, pick_files_by_ext
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
from pollux import Config, Source, run_many

PROMPTS = [
    "List 3 key themes for each video (label by source).",
    "Compare recommendations and note disagreements.",
    "Synthesize a cross-video summary in 5 bullets.",
]


def build_sources(inputs: list[str], *, max_sources: int) -> list[Source]:
    """Create Source objects from URL/file inputs."""
    sources: list[Source] = []
    for item in inputs[:max_sources]:
        value = item.strip()
        if value.lower().startswith("http"):
            sources.append(Source.from_youtube(value))
            continue

        path = Path(value)
        if path.exists() and path.is_file():
            sources.append(Source.from_file(path))
            continue

        raise SystemExit(f"Unsupported input: {item}")
    return sources


async def main_async(sources: list[Source], *, config: Config) -> None:
    envelope = await run_many(PROMPTS, sources=sources, config=config)

    answers = [str(answer) for answer in envelope.get("answers", [])]
    print_section("Multi-video result")
    print_kv_rows(
        [
            ("Status", envelope.get("status", "ok")),
            ("Sources", len(sources)),
            ("Prompts", len(PROMPTS)),
        ]
    )
    if answers:
        print_excerpt("First prompt excerpt", answers[0], limit=500)
    print_usage(envelope)
    print_learning_hints(
        [
            (
                "Next: start with two sources and scale up because attribution is usually stronger."
                if len(sources) > 2
                else "Next: tighten prompts to demand source-labeled evidence at this source count."
            ),
            "Next: keep source quality consistent to reduce noisy cross-video synthesis.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthesize insights across up to 10 video sources.",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Video file paths and/or URLs (YouTube supported).",
    )
    parser.add_argument(
        "--input-dir",
        "--input",
        type=Path,
        dest="input_dir",
        default=None,
        help="Fallback directory to auto-pick local video files.",
    )
    parser.add_argument(
        "--max-sources",
        "--limit",
        type=int,
        dest="max_sources",
        default=4,
        help="Maximum number of sources to include (cap: 10).",
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    raw_inputs = list(args.inputs)
    if not raw_inputs:
        directory = args.input_dir or DEFAULT_MEDIA_DEMO_DIR
        if not directory.exists():
            raise SystemExit(
                "No inputs found. Provide paths/URLs or run `make demo-data`."
            )
        picks = pick_files_by_ext(
            directory, [".mp4", ".mov"], limit=max(1, args.max_sources)
        )
        raw_inputs = [str(path) for path in picks]

    if not raw_inputs:
        raise SystemExit("No usable video inputs found.")

    config = build_config_or_exit(args)
    max_sources = min(10, max(1, int(args.max_sources)))
    sources = build_sources(raw_inputs, max_sources=max_sources)

    print_header("Cross-video synthesis", config=config)
    asyncio.run(main_async(sources, config=config))


if __name__ == "__main__":
    main()
