#!/usr/bin/env python3
"""🎯 Recipe: Multi-Video Batch — Compare and Summarize Across Videos

When you need to: Analyze up to 10 videos together, ask vectorized prompts,
and compare themes or recommendations across sources.

Ingredients:
- A list of up to 10 inputs: YouTube URLs and/or local MP4/MOV files
- `GEMINI_API_KEY` set in the environment

What you'll learn:
- Build mixed `Source` list (YouTube + local video files)
- Vectorize multi-question prompts with shared context
- Print per-prompt snapshots and usage

Difficulty: ⭐⭐⭐
Time: ~10-12 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from pollux import types
from pollux.extensions.provider_uploads import (
    UploadInactiveError,
    preupload_and_wait_active,
)
from pollux.frontdoor import run_batch

if TYPE_CHECKING:
    from pollux.core.result_envelope import ResultEnvelope


def _coerce_sources(items: list[str | Path]) -> list[types.Source]:
    srcs: list[types.Source] = []
    for it in items[:10]:  # cap at 10 as a sensible batch demo
        if isinstance(it, Path) or (isinstance(it, str) and Path(it).exists()):
            p = Path(it)
            # Handle video files with best-effort pre-upload for ACTIVE state
            if p.suffix.lower() in [".mp4", ".mov"]:
                try:
                    print(f"Pre-uploading video {p} and waiting for ACTIVE state...")
                    uri = preupload_and_wait_active(p)
                    srcs.append(types.Source.from_uri(uri, mime_type="video/mp4"))
                except (UploadInactiveError, RuntimeError) as e:
                    print(f"Note: video {p} not ready ({e}). Skipping for now.")
                except Exception as e:
                    print(f"Note: pre-upload unavailable ({e}); using direct upload.")
                    srcs.append(types.Source.from_file(p))
            else:
                srcs.append(types.Source.from_file(p))
        elif isinstance(it, str) and it.strip().lower().startswith("http"):
            srcs.append(types.Source.from_youtube(it))
        else:
            raise SystemExit(f"Unsupported input: {it}")
    return srcs


def _print_summary(env: ResultEnvelope) -> None:
    answers = env.get("answers", [])
    usage = env.get("usage", {})
    metrics = env.get("metrics", {})
    print(f"Answers: {len(answers)} prompts returned")
    if isinstance(usage, dict) and usage.get("total_token_count") is not None:
        print(f"🔢 Total tokens: {usage.get('total_token_count')}")
    if isinstance(metrics, dict) and metrics.get("per_prompt"):
        print("\n⏱️  Per-prompt snapshots:")
        for p in metrics["per_prompt"]:
            idx = p.get("index")
            dur = (p.get("durations") or {}).get("execute.total")
            print(f"  Prompt[{idx}] duration: {dur}s")


async def main_async(inputs: list[str | Path]) -> None:
    prompts = [
        "List 3 key themes for each video (label by source).",
        "Compare recommendations and note any disagreements.",
        "Synthesize a cross-video summary in 5 bullets.",
    ]
    sources = _coerce_sources(inputs)
    env = await run_batch(prompts, sources, prefer_json=False)
    print(f"Status: {env.get('status', 'ok')}")
    _print_summary(env)
    first = (env.get("answers") or [""])[0]
    print("\n📋 First prompt answer (first 600 chars):\n")
    print(str(first)[:600] + ("..." if len(str(first)) > 600 else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-video batch comparison")
    parser.add_argument(
        "inputs",
        nargs="+",
        help="YouTube URLs and/or local video files (max 10)",
    )
    args = parser.parse_args()
    # Normalize possible paths
    norm: list[str | Path] = [
        Path(x) if not x.startswith("http") else x for x in args.inputs
    ]
    asyncio.run(main_async(norm))


if __name__ == "__main__":
    main()
