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
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
    print_run_mode,
    usage_tokens,
)
from pollux import Config, Source, batch

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
    envelope = await batch(PROMPTS, sources=sources, config=config)

    answers = [str(answer) for answer in envelope.get("answers", [])]
    print("\nMulti-video result")
    print(f"- Status: {envelope.get('status', 'ok')}")
    print(f"- Sources: {len(sources)}")

    if answers:
        excerpt = answers[0][:500] + ("..." if len(answers[0]) > 500 else "")
        print("\nFirst prompt excerpt")
        print(excerpt)

    tokens = usage_tokens(envelope)
    if tokens is not None:
        print(f"\nUsage\n- Total tokens: {tokens}")


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
        type=Path,
        default=None,
        help="Fallback directory to auto-pick local video files.",
    )
    parser.add_argument(
        "--max-sources",
        type=int,
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

    print("Cross-video synthesis")
    print_run_mode(config)
    asyncio.run(main_async(sources, config=config))


if __name__ == "__main__":
    main()
