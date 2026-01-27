#!/usr/bin/env python3
"""🎯 Recipe: System Instructions in Efficiency Comparisons (Research Helper).

When you need to: Control system instructions while benchmarking vectorized vs
naive execution with the research helper and shared sources.

Ingredients:
- `GEMINI_API_KEY` in your environment
- A directory of files to analyze (PDFs, text, etc.)

What you'll learn:
- Set `prompts.system` and `prompts.sources_policy` via configuration
- Use `compare_efficiency(..., cfg=...)` with explicit system guidance
- Switch between `batch` and `aggregate` modes, including JSON-friendly prompts

Difficulty: ⭐⭐
Time: ~5-8 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from cookbook.utils.demo_inputs import (
    DEFAULT_TEXT_DEMO_DIR,
    pick_files_by_ext,
)
from pollux import types
from pollux.config import resolve_config
from pollux.research import compare_efficiency

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    from pollux.config.core import FrozenConfig


def make_cfg_with_system(
    *, system: str, sources_policy: str = "append_or_replace"
) -> FrozenConfig:
    """Resolve a FrozenConfig that carries a system instruction.

    - prompts.system: inline system guidance
    - prompts.sources_policy: how to compose with sources-aware guidance
      • "never": ignore sources_block entirely
      • "replace": when sources exist, use sources_block instead of system
      • "append_or_replace": append sources_block if system exists else replace
    """
    return resolve_config(
        overrides={
            "prompts.system": system,
            "prompts.sources_policy": sources_policy,
        }
    )


def default_aggregate_prompt_builder(items: list[str]) -> str:
    """Strict instruction to improve multi-answer JSON reliability."""
    n = len(items)
    header = (
        "Answer each question separately. Return only a compact JSON array of "
        f"exactly {n} items in the same order, with no additional text.\n\n"
    )
    body = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(items))
    return header + body


async def run_with_system(
    directory: Path,
    *,
    mode: str = "auto",
    trials: int = 1,
    system: str,
    builder: Callable[[list[str]], str] | None = None,
    limit: int = 2,
) -> None:
    """Run an efficiency comparison with explicit system instructions."""
    prompts = [
        "Summarize core ideas concisely.",
        "List 3 key entities.",
        "Provide 2 short quotes.",
    ]
    files = pick_files_by_ext(directory, [".pdf", ".txt"], limit=limit)
    sources = tuple(types.Source.from_file(p) for p in files)

    cfg = make_cfg_with_system(
        system=system,
        sources_policy="append_or_replace",  # Preserve system and augment with sources
    )

    def _normalize_mode(m: str) -> Literal["batch", "aggregate", "auto"]:
        return (
            "batch" if m == "batch" else ("aggregate" if m == "aggregate" else "auto")
        )

    report = await compare_efficiency(
        prompts,
        sources,
        cfg=cfg,
        mode=_normalize_mode(mode),
        trials=max(1, trials),
        warmup=1,
        include_pipeline_durations=True,
        aggregate_prompt_builder=builder,
        label="cookbook-system-instructions",
    )

    print("\n📋 System prompt in effect (inline):")
    print(system)
    print("\n📊 Efficiency Summary:")
    print(report.summary(verbose=(trials > 1), ascii_only=True))

    data = report.to_dict()
    print("\n🔎 Env snapshot (selected):")
    print(
        {
            "mode": data["env"].get("mode"),
            "vec_mode": data.get("vec_mode"),
            "prefer_json_effective": data["env"].get("prefer_json_effective"),
            "aggregate_expected_answer_count": data["env"].get(
                "aggregate_expected_answer_count"
            ),
            "aggregate_observed_answer_count": data["env"].get(
                "aggregate_observed_answer_count"
            ),
        }
    )


def main() -> None:
    """CLI entry to run the recipe interactively."""
    parser = argparse.ArgumentParser(
        description="System instructions with research helper"
    )
    parser.add_argument("--input", type=Path, default=None, help="Directory with files")
    parser.add_argument(
        "--mode",
        choices=["batch", "aggregate", "auto"],
        default="auto",
        help="Vectorized mode: multi-call batch vs single-call aggregate",
    )
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--data-dir", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--limit", type=int, default=2, help="Max files to read")
    parser.add_argument(
        "--use-default-builder",
        action="store_true",
        help="Use a strict aggregate instruction for JSON reliability",
    )
    args = parser.parse_args()
    directory = args.input or args.data_dir or DEFAULT_TEXT_DEMO_DIR
    if not directory.exists():
        raise SystemExit("No input provided. Run `make demo-data` or pass --input.")

    system = (
        "You are a careful research assistant. Be concise and factual."
        " Use numbered, consistent formatting when appropriate."
    )
    asyncio.run(
        run_with_system(
            directory,
            mode=args.mode,
            trials=args.trials,
            system=system,
            builder=default_aggregate_prompt_builder
            if args.use_default_builder
            else None,
            limit=max(1, int(args.limit)),
        )
    )


if __name__ == "__main__":
    main()
