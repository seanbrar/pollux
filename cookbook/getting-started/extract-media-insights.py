#!/usr/bin/env python3
"""Recipe: Extract fast highlights from one media source (image, audio, or video).

Problem:
    You want a quick, inspectable baseline for multimodal prompts before scaling
    to directories or synthesis workflows.

Key idea:
    Use `run_many()` to ask a small prompt set about a single source.

When to use:
    - You are iterating on multimodal prompt wording.
    - You want a small set of reliable, repeatable outputs for one media file.

When not to use:
    - You need per-file processing across many files (use the directory recipes).
    - You need multi-source synthesis (use research workflow recipes).
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
from cookbook.utils.retry import retry_async
from cookbook.utils.runtime import add_runtime_args, build_config_or_exit
from pollux import Config, Source, run_many

IMAGE_EXTS = [".png", ".jpg", ".jpeg"]
VIDEO_EXTS = [".mp4", ".mov"]
AUDIO_EXTS = [".mp3", ".wav", ".m4a", ".aac"]


def media_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTS:
        return "image"
    if suffix in VIDEO_EXTS:
        return "video"
    if suffix in AUDIO_EXTS:
        return "audio"
    return "unknown"


def prompts_for(kind: str) -> list[str]:
    if kind == "image":
        return [
            "Describe the image in 3 bullets (be concrete).",
            "List visible objects/entities and their attributes (color, size, location).",
            "If there is any text, extract it verbatim. Otherwise say 'no text'.",
        ]
    if kind == "video":
        return [
            "List 3 key moments with timestamps when visible.",
            "Identify the main entities or objects and their role in the scene.",
            "Summarize the video in 5 bullets; include any explicit claims made in the video.",
        ]
    if kind == "audio":
        return [
            "Summarize the audio in 5 bullets.",
            "List named entities mentioned and their role (person/org/product/etc).",
            "Extract 3 direct quotes (verbatim) if present; otherwise say 'no quotes'.",
        ]
    return [
        "Summarize the source in 5 bullets.",
        "List key entities and their roles.",
    ]


async def main_async(path: Path, *, config: Config) -> None:
    kind = media_kind(path)
    prompts = prompts_for(kind)
    source = Source.from_file(path)

    envelope = await retry_async(
        lambda: run_many(prompts, sources=[source], config=config),
        retries=3,
        initial_delay=1.0,
        backoff=1.8,
    )
    answers = [str(a) for a in envelope.get("answers", [])]

    print_section("Media result")
    print_kv_rows(
        [
            ("Status", envelope.get("status", "ok")),
            ("Kind", kind),
            ("Source", path),
            ("Prompts", len(prompts)),
        ]
    )
    for idx, answer in enumerate(answers, start=1):
        print_excerpt(f"Prompt {idx} excerpt", answer, limit=300)
    print_usage(envelope)
    print_learning_hints(
        [
            "Next: tighten prompts to demand evidence/attribution when outputs are vague.",
            (
                "Next: for multi-source video synthesis, move to Multi-Video Synthesis once this is stable."
                if kind == "video"
                else "Next: scale to directories with Broadcast Process Files or Large-Scale Fan-Out."
            ),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract highlights from one image, audio, or video source.",
    )
    parser.add_argument("--input", type=Path, default=None, help="Path to media file")
    add_runtime_args(parser)
    args = parser.parse_args()

    path = resolve_file_or_exit(
        args.input,
        search_dir=DEFAULT_MEDIA_DEMO_DIR,
        exts=[*VIDEO_EXTS, *IMAGE_EXTS, *AUDIO_EXTS],
        hint="No media found. Run `make demo-data` or pass --input /path/to/media.",
    )
    config = build_config_or_exit(args)

    print_header("Single-media insight extraction", config=config)
    asyncio.run(main_async(path, config=config))


if __name__ == "__main__":
    main()
