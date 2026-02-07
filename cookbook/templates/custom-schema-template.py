#!/usr/bin/env python3
"""Template: Schema-first extraction with robust JSON parsing."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from pydantic import BaseModel

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, resolve_file_or_exit
from cookbook.utils.json_tools import coerce_json
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


class MySchema(BaseModel):
    title: str
    items: list[str]


PROMPT = "Return JSON with keys: title (str), items (list[str])."


def parse_schema(answer: str) -> MySchema | None:
    """Parse model output into schema object."""
    data = coerce_json(answer)
    if data is None:
        return None
    try:
        return MySchema.model_validate(data)
    except Exception:
        return None


async def main_async(path: Path, *, config: Config) -> None:
    envelope = await run_many([PROMPT], sources=[Source.from_file(path)], config=config)
    answer = str((envelope.get("answers") or [""])[0])
    parsed = parse_schema(answer)

    print_section("Schema extraction")
    print_kv_rows(
        [
            ("Status", envelope.get("status", "ok")),
            ("Source", path),
        ]
    )
    if parsed is None:
        print_kv_rows([("Parse status", "Could not parse schema output")])
        print_excerpt("Raw excerpt", answer, limit=400)
        print_learning_hints(
            [
                "Next: strengthen schema instructions with explicit required keys and value types.",
                "Next: add deterministic examples when extraction quality is uneven.",
            ]
        )
        return

    print_kv_rows(
        [
            ("Parsed title", parsed.title),
            ("Parsed items", len(parsed.items)),
        ]
    )
    print_learning_hints(
        [
            "Next: validate every downstream field before promoting this recipe to production.",
            "Next: track parse-failure rates in tests to catch schema drift early.",
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
        hint="No input file found. Run `make demo-data` or pass --input /path/to/file.",
    )
    config = build_config_or_exit(args)

    print_header("Schema-first template", config=config)
    asyncio.run(main_async(path, config=config))


if __name__ == "__main__":
    main()
