#!/usr/bin/env python3
"""🎯 Recipe: [Problem Statement].

When you need to: [Specific scenario]

Ingredients:
- [Required setup]

What you'll learn:
- [Learning objective 1]
- [Learning objective 2]
- [Learning objective 3]

Difficulty: ⭐⭐
Time: ~X-Y minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from pollux import types
from pollux.frontdoor import run_batch

if TYPE_CHECKING:
    from pollux.core.result_envelope import ResultEnvelope


async def main_async(directory: Path) -> ResultEnvelope:
    prompts = ["[Your prompt here]"]
    sources = types.sources_from_directory(directory)
    return await run_batch(prompts, sources, prefer_json=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="[Recipe name]")
    parser.add_argument("--input", type=Path, default=None, help="Directory of files")
    args = parser.parse_args()
    directory = args.input or Path("cookbook/data/demo/text-medium")
    if not directory.exists():
        raise SystemExit("No input provided. Run `make demo-data` or pass --input.")
    env = asyncio.run(main_async(directory))
    print(env.get("status", "ok"))


if __name__ == "__main__":
    main()
