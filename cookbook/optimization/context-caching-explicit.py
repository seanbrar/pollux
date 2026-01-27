#!/usr/bin/env python3
"""🎯 Recipe: Explicit Context Caching and Token Savings

When you need to: Analyze large content repeatedly, explicitly create a cache
once, then reuse it to reduce total tokens and latency on follow-up runs.

Ingredients:
- Directory with sizable files (PDF/TXT)
- `GEMINI_API_KEY` set in the environment

What you'll learn:
- Apply `CacheOptions` + `CachePolicyHint` with a deterministic key
- Run once to warm, then reuse-only to show token savings
- Read `ResultEnvelope.metrics.per_call_meta.cache_applied` and totals

Difficulty: ⭐⭐⭐
Time: ~10-12 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from cookbook.utils.demo_inputs import (
    DEFAULT_TEXT_DEMO_DIR,
    pick_files_by_ext,
)
from pollux import types
from pollux.config import resolve_config
from pollux.core.types import InitialCommand
from pollux.executor import create_executor
from pollux.frontdoor import run_batch
from pollux.types import CacheOptions, CachePolicyHint, make_execution_options

if TYPE_CHECKING:
    from pollux.core.execution_options import ExecutionOptions
    from pollux.core.result_envelope import ResultEnvelope


async def _run(
    prompts: list[str],
    sources: tuple[types.Source, ...],
    *,
    opts: ExecutionOptions,
    executor: Any | None = None,
) -> ResultEnvelope:
    # Reuse a single executor to preserve in-memory cache registry between runs
    if executor is None:
        return await run_batch(prompts, sources, prefer_json=False, options=opts)
    cmd = InitialCommand.strict(
        sources=sources,
        prompts=tuple(prompts),
        config=executor.config,
        options=opts,
    )
    return cast("ResultEnvelope", await executor.execute(cmd))


def _tok(env: ResultEnvelope) -> int:
    u = env.get("usage") or {}
    try:
        return int(u.get("total_token_count", 0) or 0)
    except Exception:
        return 0


def _cached_tokens(env: ResultEnvelope) -> int:
    """Return cached-content tokens using best-effort fallbacks."""
    u = env.get("usage") or {}
    try:
        cc = int(u.get("cached_content_token_count", 0) or 0)
        if cc:
            return max(0, cc)
    except Exception:
        cc = 0
    # Fallback: sum per-prompt cached counts when surfaced under metrics
    m = env.get("metrics") or {}
    try:
        per = m.get("per_prompt") or ()
        total = 0
        for item in per:
            if isinstance(item, dict):
                total += int(item.get("cached_content_token_count", 0) or 0)
        return max(0, int(total))
    except Exception:
        return 0


def _cache_hits(env: ResultEnvelope) -> int:
    m = env.get("metrics") or {}
    # Prefer executor-provided aggregate when available
    agg = m.get("cache_hit_count")
    if isinstance(agg, int):
        return max(0, int(agg))
    # Fallback to per-call meta flags
    per = m.get("per_call_meta") or ()
    hits = 0
    for item in per:
        if isinstance(item, dict) and item.get("cache_applied"):
            hits += 1
    # As a last resort, treat any nonzero cached token count as one hit
    try:
        usage = env.get("usage") or {}
        if int(usage.get("cached_content_token_count", 0) or 0) > 0:
            return max(hits, 1)
    except Exception:
        pass
    return hits


async def main_async(directory: Path, cache_key: str, limit: int = 2) -> None:
    prompts = [
        "List 5 key findings with one-sentence rationale.",
        "Extract 3 actionable recommendations.",
    ]
    files = pick_files_by_ext(directory, [".pdf", ".txt"], limit=limit)
    sources = tuple(types.Source.from_file(p) for p in files)
    if not sources:
        raise SystemExit(f"No files found under {directory}")

    warm_opts = make_execution_options(
        cache=CacheOptions(
            deterministic_key=cache_key, ttl_seconds=7200, reuse_only=False
        ),
        cache_policy=CachePolicyHint(first_turn_only=True),
    )
    reuse_opts = make_execution_options(
        cache=CacheOptions(
            deterministic_key=cache_key, ttl_seconds=7200, reuse_only=True
        ),
        cache_policy=CachePolicyHint(first_turn_only=True),
    )

    # Build one executor so the cache registry persists for the second run
    cfg = resolve_config(overrides={})
    executor = create_executor(cfg)
    print("🔧 Warming cache...")
    warm = await _run(prompts, sources, opts=warm_opts, executor=executor)
    print("🔁 Reusing cache...")
    reuse = await _run(prompts, sources, opts=reuse_opts, executor=executor)

    warm_tok = _tok(warm)
    reuse_tok = _tok(reuse)
    saved = warm_tok - reuse_tok
    hits = _cache_hits(reuse)
    print("\n📊 RESULTS")
    print("Provider totals (as reported):")
    print(f"- Warm total tokens:  {warm_tok:,}")
    print(f"- Reuse total tokens: {reuse_tok:,}")
    print(
        f"- Reported savings:   {saved:,} tokens ({(saved / warm_tok * 100) if warm_tok else 0:.1f}%)"
    )

    # Effective accounting: subtract cached-content tokens when available
    cached_on_reuse = _cached_tokens(reuse)
    effective_reuse = max(reuse_tok - cached_on_reuse, 0)
    effective_saved = warm_tok - effective_reuse
    print("\nEffective totals (excluding cached content when available):")
    print(f"- Reuse effective tokens: {effective_reuse:,}")
    print(
        f"- Estimated savings:      {effective_saved:,} tokens ({(effective_saved / warm_tok * 100) if warm_tok else 0:.1f}%)"
    )

    print(f"\nCache applied on: {hits} call(s)")
    print(
        "Note: Providers may include cached tokens in totals; effective view reflects actual reuse."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit context caching demo")
    parser.add_argument("--input", type=Path, default=None, help="Directory to analyze")
    parser.add_argument("--key", default="cookbook-explicit-cache-key")
    parser.add_argument("--limit", type=int, default=2, help="Max files to read")
    parser.add_argument("--data-dir", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    directory = args.input or args.data_dir or DEFAULT_TEXT_DEMO_DIR
    if not directory.exists():
        raise SystemExit("No input provided. Run `make demo-data` or pass --input.")
    print("Note: File size/count affect runtime and tokens.")
    asyncio.run(main_async(directory, args.key, max(1, int(args.limit))))


if __name__ == "__main__":
    main()
