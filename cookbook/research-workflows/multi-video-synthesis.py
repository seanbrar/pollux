#!/usr/bin/env python3
"""Recipe: Synthesize one decision-ready brief across several videos.

Problem:
    You have a handful of talks or clips and need one consolidated read —
    what they agree on, where they disagree, and what to watch first — without
    scrubbing through every minute yourself.

Pattern:
    - Fan-in: many sources collapse into one synthesis (run_many with one
      prompt and shared sources).
    - YouTube-first: `Source.from_youtube()` ingests URLs with no download, so
      the recipe needs zero local media. Local files work too, via --input.
    - Structured output: a Pydantic response schema turns the synthesis into a
      typed, source-attributed artifact instead of prose you have to re-parse.

When to use:
    - You want a cross-video comparison with explicit source attribution.

When not to use:
    - You only have one source (use extract-media-insights).
    - You need a provider without YouTube ingestion. YouTube URL inputs are
      supported on Gemini; see docs/reference/provider-capabilities.md.

Run (mock, zero setup):
    python -m cookbook research-workflows/multi-video-synthesis

Run (live synthesis across YouTube videos, Gemini):
    python -m cookbook research-workflows/multi-video-synthesis \\
      --input https://youtu.be/VIDEO_ONE https://youtu.be/VIDEO_TWO \\
      --no-mock --provider gemini

Success check:
    - Output includes shared themes, tensions, one take per source, a
      watch-first pick, and a short synthesis.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from cookbook.utils.demo_inputs import pick_files_by_ext
from cookbook.utils.presentation import (
    print_excerpt,
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
    print_usage,
)
from cookbook.utils.runtime import add_runtime_args, build_config_or_exit
from pollux import Config, Options, Source, run_many

VIDEO_EXTS = [".mp4", ".mov", ".webm", ".mkv"]
MAX_SOURCES = 10

# Placeholder URLs so the default `--mock` run works with zero setup. They are
# not real videos: in mock mode nothing is fetched, so they only stand in to
# show the synthesis shape. For a live run, pass real --input URLs or files.
EXAMPLE_SOURCES = [
    "https://www.youtube.com/watch?v=pollux-example-talk-a",
    "https://www.youtube.com/watch?v=pollux-example-talk-b",
]


class SourceTake(BaseModel):
    source: str = Field(description="Short label for the source (URL or filename).")
    angle: str = Field(description="What this source uniquely emphasizes.")
    standout: str = Field(description="The single strongest point from this source.")


class VideoSynthesis(BaseModel):
    headline: str = Field(description="Short title for the cross-video synthesis.")
    shared_themes: list[str] = Field(
        description="Themes most sources agree on, with source labels."
    )
    tensions: list[str] = Field(
        description="Where sources disagree or differ in emphasis."
    )
    per_source: list[SourceTake] = Field(
        description="One take per source, in input order."
    )
    watch_first: str = Field(description="Which source to watch first and why.")
    tldr: str = Field(description="2-3 sentence synthesis across all sources.")


def source_label(value: str) -> str:
    """Return a compact display/attribution label for a URL or file path."""
    if value.lower().startswith("http"):
        return value
    return Path(value).name


def build_sources(values: list[str]) -> tuple[list[Source], list[str]]:
    """Build Source objects (and attribution labels) from URLs or file paths."""
    sources: list[Source] = []
    labels: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned.lower().startswith("http"):
            sources.append(Source.from_youtube(cleaned))
        else:
            path = Path(cleaned)
            if not path.is_file():
                raise SystemExit(
                    f"Input not found (expected a URL or an existing file): {value}"
                )
            sources.append(Source.from_file(path))
        labels.append(source_label(cleaned))
    return sources, labels


def build_prompt(labels: list[str]) -> str:
    """Return the fan-in synthesis prompt with explicit source labels."""
    joined = "; ".join(f"[{idx}] {label}" for idx, label in enumerate(labels, start=1))
    return (
        "You are synthesizing across several videos for someone deciding what to "
        "watch and what to take away. "
        f"Sources, in order: {joined}. "
        "Attribute every claim to its source. Surface the shared themes, the real "
        "disagreements or differences in emphasis, one standout take per source, "
        "which source to watch first, and a short overall synthesis."
    )


def mock_synthesis(labels: list[str]) -> VideoSynthesis:
    """Return a deterministic synthesis artifact for mock mode."""
    first = labels[0] if labels else "source-1"
    return VideoSynthesis(
        headline=f"Cross-video synthesis of {len(labels)} sources",
        shared_themes=[
            "All sources can be compared on the same axis once they are labeled.",
            "Each source needs attribution before its claims feed a decision.",
        ],
        tensions=[
            f"{first} may frame the topic differently from the others — check before merging.",
        ],
        per_source=[
            SourceTake(
                source=label,
                angle=f"What [{idx}] uniquely emphasizes goes here.",
                standout=f"The strongest single point from {label}.",
            )
            for idx, label in enumerate(labels, start=1)
        ],
        watch_first=f"Start with {first}: it anchors the shared themes for the rest.",
        tldr=(
            "A live run replaces this with a real cross-video read: shared themes, "
            "genuine disagreements, and a watch-first recommendation."
        ),
    )


def print_synthesis(synthesis: VideoSynthesis) -> None:
    """Print the structured synthesis in a compact, scannable form."""
    print_section("Synthesis")
    print(f"  {synthesis.headline}")
    print(f"  {synthesis.tldr}")

    print_section("Shared themes")
    for theme in synthesis.shared_themes:
        print(f"- {theme}")

    print_section("Tensions")
    for tension in synthesis.tensions:
        print(f"- {tension}")

    print_section("Per-source takes")
    for take in synthesis.per_source:
        print(f"- {take.source}")
        print(f"  Angle: {take.angle}")
        print(f"  Standout: {take.standout}")

    print_section("Watch first")
    print(f"  {synthesis.watch_first}")


async def main_async(
    sources: list[Source], labels: list[str], *, config: Config
) -> None:
    prompt = build_prompt(labels)
    if config.use_mock:
        # Exercise one real pipeline call, then render a deterministic artifact:
        # the mock provider does not produce structured output.
        envelope = await run_many([prompt], sources=sources, config=config)
        synthesis: VideoSynthesis | None = mock_synthesis(labels)
    else:
        options = Options(response_schema=VideoSynthesis)
        envelope = await run_many(
            [prompt], sources=sources, config=config, options=options
        )
        structured = envelope.get("structured") or []
        first = structured[0] if structured else None
        synthesis = first if isinstance(first, VideoSynthesis) else None

    answer = str((envelope.get("answers") or [""])[0])

    print_section("Multi-video synthesis")
    print_kv_rows(
        [
            ("Status", envelope.get("status", "ok")),
            ("Sources", len(sources)),
        ]
    )

    if not isinstance(synthesis, VideoSynthesis):
        print_kv_rows([("Structured output", "No validated synthesis returned")])
        print_excerpt("Raw excerpt", answer, limit=400)
        print_usage(envelope)
        print_learning_hints(
            [
                "Next: choose a provider/model with structured output support.",
                "Next: keep the source set small so attribution stays sharp.",
            ]
        )
        return

    print_synthesis(synthesis)
    print_usage(envelope)
    print_learning_hints(
        [
            "Next: swap in your own YouTube URLs with --input and rerun with --no-mock.",
            "Next: feed this synthesis into a second Pollux call to draft a watch guide.",
        ]
    )


def resolve_inputs(
    raw_inputs: list[str], *, max_sources: int
) -> tuple[list[str], bool]:
    """Resolve CLI inputs into source values, noting if examples were used.

    A single directory is expanded into its video files. With no inputs, fall
    back to placeholder example URLs (usable in mock mode for a zero-setup run).
    """
    values = list(raw_inputs)
    if len(values) == 1 and Path(values[0]).is_dir():
        picks = pick_files_by_ext(Path(values[0]), VIDEO_EXTS, limit=max_sources)
        if not picks:
            raise SystemExit(f"No video files found under: {values[0]}")
        return [str(path) for path in picks], False
    if not values:
        return list(EXAMPLE_SOURCES[:max_sources]), True
    return values[:max_sources], False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthesize one brief across several YouTube videos or files.",
    )
    parser.add_argument(
        "--input",
        nargs="+",
        default=None,
        help="YouTube URLs, video file paths, or a single directory to auto-pick from.",
    )
    parser.add_argument(
        "--max-sources",
        "--limit",
        type=int,
        dest="max_sources",
        default=4,
        help=f"Maximum number of sources to include (cap: {MAX_SOURCES}).",
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    config = build_config_or_exit(args)
    max_sources = min(MAX_SOURCES, max(1, int(args.max_sources)))
    values, using_examples = resolve_inputs(
        list(args.input) if args.input else [], max_sources=max_sources
    )

    if using_examples and not config.use_mock:
        raise SystemExit(
            "multi-video-synthesis needs real sources for a live run.\n"
            "Pass --input with two or more YouTube URLs or local video files, e.g.:\n"
            "  python -m cookbook research-workflows/multi-video-synthesis \\\n"
            "    --input https://youtu.be/VIDEO_ONE https://youtu.be/VIDEO_TWO --no-mock\n"
            "YouTube URL inputs are supported on Gemini."
        )

    sources, labels = build_sources(values)

    print_header("Cross-video synthesis", config=config)
    asyncio.run(main_async(sources, labels, config=config))


if __name__ == "__main__":
    main()
