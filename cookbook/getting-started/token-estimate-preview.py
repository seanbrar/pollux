#!/usr/bin/env python3
"""🎯 Recipe: Token Estimate Preview Before Running a Batch.

When you need to: Forecast token usage and cost for a batch, compare to a
budget, and decide whether to run now, downscope, or adjust concurrency.

Ingredients:
- Environment config resolved by `pollux.config` (model/tier)
- Directory of files (or text) to analyze
- Optional token or dollar budget

What you'll learn:
- Use Gemini token counting (with fallback) to estimate batch usage
- Apply conservative widening/clamping via EstimationOptions
- Make an informed go/no-go decision before spending

Difficulty: ⭐⭐
Time: ~5-8 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import mimetypes
import os
from pathlib import Path
import string
from typing import TYPE_CHECKING

from cookbook.utils.demo_inputs import DEFAULT_TEXT_DEMO_DIR
from pollux.config import resolve_config
from pollux.extensions.token_counting import (
    TokenCountFailure,
    TokenCountResult,
    ValidContent,
    count_gemini_tokens,
)
from pollux.types import EstimationOptions

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass
class EstimateSummary:
    total_tokens: int
    per_source: dict[str, int]
    prompts: list[str]
    model: str
    budget_tokens: int | None


_TEXT_EXTS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".csv",
    ".json",
    ".jsonl",
    ".toml",
    ".yaml",
    ".yml",
    ".tex",
}


def _looks_textual(path: Path) -> bool:
    """Heuristic: treat obvious text files as textual; skip media/binary.

    - Allow if mimetype startswith text/
    - Also allow common text extensions
    - Explicitly skip images/audio/video and application/pdf by default
    """
    ext = path.suffix.lower()
    if ext in _TEXT_EXTS:
        return True
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        if mime.startswith("text/"):
            return True
        if mime.startswith(("image/", "audio/", "video/")):
            return False
        # Skip PDFs by default unless pre-extracted
        if mime == "application/pdf":
            return False
    # Fallback: small files with mostly printable chars
    try:
        data = path.read_bytes()
        if len(data) > 256_000:  # 256 KB cap for heuristic sniff
            return False
        text = data.decode("utf-8", errors="ignore")
        printable = sum(1 for c in text if c in string.printable)
        return (len(text) > 0) and (printable / max(len(text), 1) > 0.85)
    except Exception:
        return False


def _iter_texts_from_directory(root: Path) -> Iterable[tuple[str, str]]:
    """Yield (id, text) for clearly textual files only.

    This avoids wildly overestimating by decoding binary/media files.
    """
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if not _looks_textual(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
            yield (str(p), text)
        except Exception:
            continue


async def _estimate_text_tokens(text: str, model_name: str) -> int:
    """Return token estimate using Gemini counter or a simple fallback."""
    try:
        vc = ValidContent.from_text(text)
        # Conservative widening for safety (e.g., +25%), clamp at a sane ceiling
        hints = (EstimationOptions(widen_max_factor=1.25, clamp_max_tokens=2_000_000),)
        res: TokenCountResult = await count_gemini_tokens(vc.text, model_name, hints)
        if isinstance(res, TokenCountFailure):
            # Fallback heuristic ~4 chars/token
            return max(1, len(text) // 4)
        return int(res.count)
    except Exception:
        return max(1, len(text) // 4)


async def estimate_directory(
    directory: Path, prompts: list[str], *, budget_tokens: int | None = None
) -> EstimateSummary:
    cfg = resolve_config()
    model = cfg.model

    per_source: dict[str, int] = {}
    total_source_tokens = 0

    for sid, text in _iter_texts_from_directory(directory):
        t = await _estimate_text_tokens(text, model)
        per_source[sid] = t
        total_source_tokens += t

    # Very rough prompt/system overhead per question (~30 tokens) for planning
    questions = max(1, len(prompts))
    overhead_per_prompt = 30
    total_tokens = total_source_tokens * questions + overhead_per_prompt * questions

    return EstimateSummary(
        total_tokens=total_tokens,
        per_source=per_source,
        prompts=prompts,
        model=model,
        budget_tokens=budget_tokens,
    )


def _as_dollars(tokens: int, *, dollars_per_million: float = 1.0) -> float:
    # Replace with your negotiated rate; placeholder $1 / 1M tokens
    return (tokens / 1_000_000.0) * dollars_per_million


def main() -> None:
    parser = argparse.ArgumentParser(description="Token estimate preview")
    parser.add_argument(
        "directory",
        type=Path,
        nargs="?",
        help="Directory with input files to estimate",
    )
    parser.add_argument(
        "--question",
        action="append",
        default=["Summarize the key ideas succinctly."],
        help="Add one or more prompts (repeat flag)",
    )
    parser.add_argument(
        "--budget-tokens",
        type=int,
        default=int(os.environ.get("GEMINI_BUDGET_TOKENS", "0") or 0) or None,
        help="Optional token budget; abort if estimate exceeds",
    )
    parser.add_argument(
        "--save-json",
        type=Path,
        default=None,
        help="Optional path to write a JSON estimate report",
    )
    args = parser.parse_args()

    directory = args.directory or DEFAULT_TEXT_DEMO_DIR
    if not directory.exists():
        raise SystemExit("No input provided. Run `make demo-data` or pass a directory.")

    summary = asyncio.run(
        estimate_directory(
            directory,
            prompts=list(args.question),
            budget_tokens=args.budget_tokens,
        )
    )

    dollars = _as_dollars(summary.total_tokens, dollars_per_million=1.0)
    print("📊 ESTIMATE PREVIEW")
    print(f"Model: {summary.model}")
    print(f"Prompts: {len(summary.prompts)}")
    print(f"Estimated tokens: {summary.total_tokens:,}")
    print(f"Approx cost (@$1/1M): ${dollars:.4f}")

    if summary.budget_tokens is not None:
        ok = summary.total_tokens <= summary.budget_tokens
        print(
            f"Budget tokens: {summary.budget_tokens:,} -> {'OK' if ok else 'EXCEEDS'}"
        )
        if not ok:
            print("❌ Exceeds budget. Consider reducing sources, prompts, or chunking.")
        else:
            print("✅ Within budget. Safe to proceed.")

    if args.save_json:
        report = {
            "model": summary.model,
            "prompts": summary.prompts,
            "total_tokens": summary.total_tokens,
            "per_source_tokens": summary.per_source,
            "budget_tokens": summary.budget_tokens,
        }
        args.save_json.parent.mkdir(parents=True, exist_ok=True)
        args.save_json.write_text(json.dumps(report, indent=2))
        print(f"💾 Wrote estimate report to {args.save_json}")


if __name__ == "__main__":
    main()
