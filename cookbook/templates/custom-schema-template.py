#!/usr/bin/env python3
"""Template: Schema-first extraction with a Pydantic response schema.

Copy this file when a recipe needs typed, validated output. Replace:
- The `MySchema` fields with your own.
- The `PROMPT` with a concrete extraction instruction.
- The `mock_preview()` body so mock runs show a realistic shape.

Why a response schema (not hand-parsed JSON):
    Pass a Pydantic model via `Options(response_schema=...)`. Pollux asks the
    provider for structured output (when supported) and returns validated
    objects in `envelope["structured"]` alongside the raw `answers`. This is the
    pattern every schema-using recipe in the cookbook follows.
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


class MySchema(BaseModel):
    title: str = Field(description="A short title for the source.")
    items: list[str] = Field(description="3-6 extracted items.")


PROMPT = "Extract a title and key items from the source. Be specific."


def mock_preview(path: Path) -> MySchema:
    """Return a realistic schema instance for mock-mode runs."""
    return MySchema(
        title=f"(mock preview) {path.stem}",
        items=["example item 1", "example item 2", "example item 3"],
    )


async def main_async(path: Path, *, config: Config) -> None:
    if config.use_mock:
        # The mock provider does not produce structured output; exercise one real
        # call, then render a deterministic preview so the schema shape is visible.
        envelope = await run(PROMPT, source=Source.from_file(path), config=config)
        parsed: MySchema | None = mock_preview(path)
    else:
        envelope = await run(
            PROMPT,
            source=Source.from_file(path),
            config=config,
            options=Options(response_schema=MySchema),
        )
        structured = envelope.structured or []
        first = structured[0] if structured else None
        parsed = first if isinstance(first, MySchema) else None

    print_section("Schema extraction")
    print_kv_rows(
        [
            ("Status", envelope.metrics.completion_status),
            ("Source", path),
        ]
    )

    if not isinstance(parsed, MySchema):
        answer = envelope.text
        print_kv_rows([("Structured output", "No validated object returned")])
        print_excerpt("Raw excerpt", answer, limit=400)
        print_usage(envelope)
        print_learning_hints(
            [
                "Next: try a provider/model that supports structured outputs.",
                "Next: tighten the schema and prompt if fields are missing.",
            ]
        )
        return

    print_kv_rows(
        [
            ("Parsed title", parsed.title),
            ("Parsed items", len(parsed.items)),
        ]
    )
    print_usage(envelope)
    print_learning_hints(
        [
            "Next: add field constraints (enums, min/max lengths) once the shape is stable.",
            "Next: track validation-failure rates as a first-class metric.",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Schema-first extraction template")
    parser.add_argument(
        "--input", type=Path, default=None, help="Path to an input file"
    )
    add_runtime_args(parser)
    args = parser.parse_args()

    path = resolve_file_or_exit(
        args.input,
        search_dir=DEFAULT_TEXT_DEMO_DIR,
        exts=[".txt", ".md", ".pdf"],
        hint="No input file found. Run `just demo-data` or pass --input /path/to/file.",
    )
    config = build_config_or_exit(args)

    print_header("Schema-first template", config=config)
    asyncio.run(main_async(path, config=config))


if __name__ == "__main__":
    main()
