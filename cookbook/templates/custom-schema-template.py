#!/usr/bin/env python3
"""Template: Schema-first extraction with robust JSON parsing."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from pydantic import BaseModel

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, resolve_file_or_exit
from cookbook.utils.json_tools import coerce_json
from cookbook.utils.runtime import (
    add_runtime_args,
    build_config_or_exit,
    print_run_mode,
)
from pollux import Config, Source, batch


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
    envelope = await batch([PROMPT], sources=[Source.from_file(path)], config=config)
    answer = str((envelope.get("answers") or [""])[0])
    parsed = parse_schema(answer)

    print("\nSchema extraction")
    print(f"- Status: {envelope.get('status', 'ok')}")
    print(f"- Source: {path}")
    if parsed is None:
        excerpt = answer[:400] + ("..." if len(answer) > 400 else "")
        print("- Could not parse schema. Raw excerpt:")
        print(excerpt)
        return

    print("- Parsed title:", parsed.title)
    print("- Parsed items:", len(parsed.items))


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

    print("Schema-first template")
    print_run_mode(config)
    asyncio.run(main_async(path, config=config))


if __name__ == "__main__":
    main()
