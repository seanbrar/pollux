#!/usr/bin/env python3
"""Recipe: Turn two sources into a structured comparison brief.

Problem:
    You need a decision-ready brief that compares two documents without
    hand-parsing model prose.

Pattern:
    - Send both sources as shared context.
    - Use a Pydantic response schema for the comparison artifact.
    - Print the strongest differences and follow-up questions.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR
from cookbook.utils.presentation import (
    print_excerpt,
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
)
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
)
from pollux import Config, Source, run_many

PROMPT = (
    "Compare these sources for a project lead deciding what to do next. "
    "Focus on concrete overlaps, disagreements, strengths, weaknesses, and "
    "follow-up questions that would change the decision."
)


class ComparisonBrief(BaseModel):
    title: str = Field(description="Short title for the comparison brief.")
    similarities: list[str] = Field(description="Concrete overlaps between sources.")
    differences: list[str] = Field(description="Important disagreements or contrasts.")
    source_a_strengths: list[str] = Field(
        description="Where the first source is stronger."
    )
    source_b_strengths: list[str] = Field(
        description="Where the second source is stronger."
    )
    follow_up_questions: list[str] = Field(
        description="Questions worth answering before making a decision."
    )


def mock_brief(paths: list[Path]) -> ComparisonBrief:
    """Return a deterministic artifact preview for mock mode."""
    left = paths[0].stem if paths else "source-a"
    right = paths[1].stem if len(paths) > 1 else "source-b"
    return ComparisonBrief(
        title=f"{left} vs {right}",
        similarities=[
            "Both sources discuss the same project space and can be compared side by side.",
            "Both need source-labeled evidence before a project lead should act.",
        ],
        differences=[
            f"{left} should be checked for claims that are absent from {right}.",
            f"{right} may contain constraints or caveats missing from {left}.",
        ],
        source_a_strengths=[f"{left} can anchor the first half of the brief."],
        source_b_strengths=[f"{right} can supply contrast and missing context."],
        follow_up_questions=[
            "Which difference would change the next implementation decision?",
        ],
    )


async def main_async(paths: list[Path], *, config: Config) -> None:
    sources = [Source.from_file(path) for path in paths]
    if config.use_mock:
        # Exercise one real pipeline call, then render a deterministic artifact:
        # the mock provider does not produce structured output.
        envelope = await run_many([PROMPT], sources=sources, config=config)
        brief: ComparisonBrief | None = mock_brief(paths)
    else:
        envelope = await run_many(
            [PROMPT], sources=sources, config=config, output=ComparisonBrief
        )
        structured = envelope.structured or []
        first = structured[0] if structured else None
        brief = first if isinstance(first, ComparisonBrief) else None

    answer = str((envelope.answers or [""])[0])

    print_section("Comparison brief")
    print_kv_rows(
        [
            ("Status", envelope.status),
            ("Sources", ", ".join(str(path) for path in paths)),
        ]
    )

    if not isinstance(brief, ComparisonBrief):
        print_kv_rows([("Structured output", "No validated brief returned")])
        print_excerpt("Raw excerpt", answer, limit=400)
        print_learning_hints(
            [
                "Next: choose a provider/model with structured output support.",
                "Next: keep source scope narrow so comparison fields stay concrete.",
            ]
        )
        return

    print_kv_rows(
        [
            ("Title", brief.title),
            (
                "Counts",
                " ".join(
                    [
                        f"similarities={len(brief.similarities)}",
                        f"differences={len(brief.differences)}",
                        f"a_strengths={len(brief.source_a_strengths)}",
                        f"b_strengths={len(brief.source_b_strengths)}",
                        f"questions={len(brief.follow_up_questions)}",
                    ]
                ),
            ),
        ]
    )
    if brief.differences:
        print_kv_rows([("First key difference", brief.differences[0])])
    if brief.follow_up_questions:
        print_excerpt(
            "Best follow-up question", brief.follow_up_questions[0], limit=240
        )
    print_learning_hints(
        [
            "Next: adapt the schema fields to your decision criteria.",
            "Next: feed this brief into a second Pollux call to draft an action plan.",
        ]
    )


def pick_paths(directory: Path, limit: int) -> list[Path]:
    """Select deterministic files from a directory up to a limit."""
    candidates = sorted(path for path in directory.rglob("*") if path.is_file())
    if len(candidates) < 2:
        raise SystemExit(f"Need at least two files under: {directory}")
    return candidates[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Produce a structured source-to-source comparison.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        default=None,
        help="Two or more input files, or a single directory to auto-pick from.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2,
        help="Max files to compare (default: 2)",
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    inputs: list[Path] = list(args.input) if args.input else []
    if len(inputs) == 1 and inputs[0].is_dir():
        paths = pick_paths(inputs[0], args.limit)
    elif len(inputs) >= 2:
        paths = inputs
    else:
        if not DEFAULT_TEXT_DEMO_DIR.exists():
            raise SystemExit(
                "Need two files. Run `just demo-data` or provide --input with two paths."
            )
        paths = pick_paths(DEFAULT_TEXT_DEMO_DIR, args.limit)

    config = build_config_or_exit(args)
    print_header("Research comparison baseline", config=config)
    asyncio.run(main_async(paths[: args.limit], config=config))


if __name__ == "__main__":
    main()
