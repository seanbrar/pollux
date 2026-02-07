#!/usr/bin/env python3
"""Recipe: Extract structured outputs with a schema (Pydantic) instead of parsing JSON by hand.

Problem:
    You want to turn model output into a typed object that downstream code can trust.

Key idea:
    Pass a Pydantic model class via `Options(response_schema=...)`. Pollux will:
    - ask the provider for structured JSON output (when supported)
    - return `envelope["structured"]` alongside the raw `answers`

When to use:
    - You are building a pipeline that needs validated fields.
    - You want to measure parse/validation failure rates over time.

When not to use:
    - You are still exploring prompt shape (start with free-form text).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, resolve_file_or_exit
from cookbook.utils.presentation import (
    print_excerpt,
    print_header,
    print_kv_rows,
    print_learning_hints,
    print_section,
    print_usage,
)
from cookbook.utils.runtime import add_runtime_args, build_config_or_exit
from pollux import Config, Options, Source, run


class KeyPoints(BaseModel):
    title: str = Field(description="A short title for the source.")
    bullets: list[str] = Field(description="3-6 key points.")
    risks: list[str] = Field(description="2-4 risks, limitations, or caveats.")


PROMPT = (
    "Extract key points from the source. Be specific and avoid generic boilerplate."
)


async def main_async(path: Path, *, config: Config) -> None:
    if config.use_mock:
        # Mock provider does not advertise structured-output capability; validate the
        # schema wiring by creating a small example payload locally.
        envelope = await run(PROMPT, source=Source.from_file(path), config=config)
        parsed: KeyPoints | None = KeyPoints(
            title=f"(mock) {path.stem}",
            bullets=["example bullet 1", "example bullet 2", "example bullet 3"],
            risks=["example risk 1", "example risk 2"],
        )
    else:
        envelope = await run(
            PROMPT,
            source=Source.from_file(path),
            config=config,
            options=Options(response_schema=KeyPoints),
        )
        structured = envelope.get("structured")
        parsed = None
        if isinstance(structured, list) and structured:
            raw = structured[0]
            parsed = raw if isinstance(raw, KeyPoints) else None

    print_section("Result")
    print_kv_rows(
        [
            ("Status", envelope.get("status", "ok")),
            ("Source", path),
        ]
    )

    if parsed is None:
        print_kv_rows([("Parse status", "No structured output returned")])
        answers = [str(a) for a in envelope.get("answers", [])]
        if answers:
            print_excerpt("Raw excerpt", answers[0], limit=400)
        print_usage(envelope)
        print_learning_hints(
            [
                "Next: try a provider/model that supports structured outputs.",
                "Next: tighten the schema and prompt if fields are missing.",
            ]
        )
        return

    payload = parsed.model_dump()

    print_section("Structured output")
    if isinstance(payload, dict):
        print_kv_rows(
            [
                ("title", payload.get("title")),
                ("bullets", len(payload.get("bullets", []) or [])),
                ("risks", len(payload.get("risks", []) or [])),
            ]
        )
    else:
        print_kv_rows([("structured[0] type", type(parsed).__name__)])

    answers = [str(a) for a in envelope.get("answers", [])]
    if answers:
        print_excerpt("Raw answer excerpt", answers[0], limit=260)
    print_usage(envelope)
    print_learning_hints(
        [
            "Next: treat schema validation failures as first-class metrics (track and alert).",
            "Next: add stronger field constraints (enums, min/max lengths) once shape is stable.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract structured key points using a Pydantic response schema.",
    )
    parser.add_argument(
        "--input", type=Path, default=None, help="Path to a source file"
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    path = resolve_file_or_exit(
        args.input,
        search_dir=DEFAULT_TEXT_DEMO_DIR,
        exts=[".pdf", ".txt", ".md"],
        hint="No input found. Run `make demo-data` or pass --input /path/to/file.",
    )
    config = build_config_or_exit(args)

    print_header("Structured outputs: schema-first extraction", config=config)
    asyncio.run(main_async(path, config=config))


if __name__ == "__main__":
    main()
