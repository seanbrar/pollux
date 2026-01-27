#!/usr/bin/env python3
"""🎯 Template: Schema-First Extraction.

When you need to: Ask for structured JSON and parse into a Pydantic model.

Note:
- This template uses a tiny helper (`cookbook.utils.json_tools.coerce_json`) to
  extract JSON robustly even when answers are wrapped in Markdown fences or
  include minor formatting noise, then validates it with Pydantic.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from pydantic import BaseModel

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR, pick_file_by_ext
from cookbook.utils.json_tools import coerce_json
from pollux import types
from pollux.frontdoor import run_batch


class MySchema(BaseModel):
    title: str
    items: list[str]


PROMPT = "Return JSON with keys: title (str), items (list[str])."


def _parse(answer: str) -> MySchema | None:
    data = coerce_json(answer)
    if data is None:
        return None
    try:
        return MySchema.model_validate(data)
    except Exception:
        return None


async def main_async(path: Path) -> None:
    src = types.Source.from_file(path)
    env = await run_batch([PROMPT], [src], prefer_json=True)
    ans = (env.get("answers") or [""])[0]
    data = _parse(str(ans))
    if data:
        print("✅ Parsed JSON successfully:")
        print(data)
    else:
        print("⚠️ Could not parse JSON (likely in mock mode). Raw response:")
        print(str(ans)[:400])


def main() -> None:
    parser = argparse.ArgumentParser(description="Schema-first extraction template")
    parser.add_argument("--input", type=Path, default=None, help="Path to a file")
    args = parser.parse_args()
    path = args.input
    if path is None:
        base = DEFAULT_TEXT_DEMO_DIR
        if not base.exists():
            raise SystemExit("No input provided. Run `make demo-data` or pass --input.")
        path = pick_file_by_ext(base, [".txt", ".md", ".pdf"]) or None
        if path is None:
            raise SystemExit(
                "No suitable files in demo dir. Run `make demo-data` or pass --input."
            )
    asyncio.run(main_async(path))


if __name__ == "__main__":
    main()
