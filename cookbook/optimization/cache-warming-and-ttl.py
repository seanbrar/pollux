#!/usr/bin/env python3
"""🎯 Recipe: Cache Warming with Deterministic Keys and TTL

When you need to: Pre-warm shared context caches and then reuse them to
reduce latency and tokens across repeated analyses.

Ingredients:
- Set `enable_caching=True` in config (env or override)
- Deterministic cache key for the shared context
- Representative prompts and a directory of files

What you'll learn:
- Apply `CacheOptions` (deterministic key, TTL, reuse-only)
- Compare warm vs reuse timings and token usage
- Understand first-turn-only and token floor policy knobs

Difficulty: ⭐⭐⭐
Time: ~10-12 minutes
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


def _count_hits_from_metrics(m: dict[str, Any]) -> int:
    # Prefer aggregate if available; fallback to per-call meta
    agg = m.get("cache_hit_count")
    if isinstance(agg, int):
        return max(0, int(agg))
    pcm = m.get("per_call_meta") or ()
    hits = 0
    for item in pcm:
        if isinstance(item, dict) and item.get("cache_applied"):
            hits += 1
    return hits


async def _run(
    prompts: list[str],
    sources: tuple[types.Source, ...],
    *,
    opts: ExecutionOptions,
    executor: Any | None = None,
) -> dict[str, Any]:
    if executor is None:
        env = await run_batch(prompts, sources, prefer_json=False, options=opts)
    else:
        cmd = InitialCommand.strict(
            sources=sources,
            prompts=tuple(prompts),
            config=executor.config,
            options=opts,
        )
        env = await executor.execute(cmd)
    return {
        "status": env.get("status", "ok"),
        "usage": env.get("usage", {}),
        "metrics": env.get("metrics", {}),
    }


def _tokens(usage: dict[str, Any]) -> int:
    try:
        return int((usage or {}).get("total_token_count", 0) or 0)
    except Exception:
        return 0


def _cached_tokens(metrics: dict[str, Any], usage: dict[str, Any]) -> int:
    """Return cached-content tokens using best-effort fallbacks."""
    try:
        cc = int(usage.get("cached_content_token_count", 0) or 0)
        if cc:
            return max(0, cc)
    except Exception:
        pass
    try:
        per = metrics.get("per_prompt") or ()
        total = 0
        for item in per:
            if isinstance(item, dict):
                total += int(item.get("cached_content_token_count", 0) or 0)
        return max(0, int(total))
    except Exception:
        return 0


async def main_async(directory: Path, cache_key: str, limit: int = 2) -> None:
    cfg = resolve_config(overrides={"enable_caching": True})
    print(f"⚙️  Caching enabled: {cfg.enable_caching}")

    prompts = [
        "List 5 key concepts with one-sentence explanations.",
        "Extract three actionable recommendations.",
    ]
    files = pick_files_by_ext(directory, [".pdf", ".txt"], limit=limit)
    sources = tuple(types.Source.from_file(p) for p in files)
    if not sources:
        raise SystemExit(f"No files found under {directory}")

    # Warm: allow create
    warm_opts = make_execution_options(
        cache=CacheOptions(
            deterministic_key=cache_key, ttl_seconds=3600, reuse_only=False
        ),
        cache_policy=CachePolicyHint(first_turn_only=True),
    )
    # Reuse a single executor so the in-memory registry persists
    executor = create_executor(cfg)
    warm = await _run(prompts, sources, opts=warm_opts, executor=executor)

    # Reuse: reuse-only true
    reuse_opts = make_execution_options(
        cache=CacheOptions(
            deterministic_key=cache_key, ttl_seconds=3600, reuse_only=True
        ),
        cache_policy=CachePolicyHint(first_turn_only=True),
    )
    reuse = await _run(prompts, sources, opts=reuse_opts, executor=executor)

    w_tok = _tokens(warm.get("usage", {}))
    r_tok = _tokens(reuse.get("usage", {}))
    w_hits = _count_hits_from_metrics(warm.get("metrics", {}) or {})
    r_hits = _count_hits_from_metrics(reuse.get("metrics", {}) or {})
    print("\n📊 RESULTS")
    print("Provider totals (as reported):")
    print(f"- Warm:  status={warm['status']} | tokens={w_tok:,}")
    print(f"- Reuse: status={reuse['status']} | tokens={r_tok:,}")
    if w_hits or r_hits:
        print(f"- Cache hits (warm→reuse): {w_hits} → {r_hits}")

    # Effective accounting for reuse
    reuse_cached = _cached_tokens(
        reuse.get("metrics", {}) or {}, reuse.get("usage", {}) or {}
    )
    effective_reuse = max(r_tok - reuse_cached, 0)
    est_saved = w_tok - effective_reuse
    print("\nEffective totals (excluding cached content when available):")
    print(f"- Reuse effective tokens: {effective_reuse:,}")
    print(
        f"- Estimated savings:      {est_saved:,} tokens ({(est_saved / w_tok * 100) if w_tok else 0:.1f}%)"
    )

    print(
        "\nNote: Providers may include cached tokens in totals; effective view reflects actual reuse."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Cache warming and TTL demo")
    parser.add_argument(
        "--input", type=Path, default=None, help="Directory to cache context from"
    )
    parser.add_argument("--limit", type=int, default=2, help="Max files to read")
    parser.add_argument(
        "--key",
        default="cookbook-cache-key",
        help="Deterministic cache key to use",
    )
    args = parser.parse_args()
    print("Note: File size/count affect runtime and tokens.")
    directory = args.input or DEFAULT_TEXT_DEMO_DIR
    if not directory.exists():
        raise SystemExit("No input provided. Run `make demo-data` or pass --input.")
    asyncio.run(main_async(directory, args.key, max(1, int(args.limit))))


if __name__ == "__main__":
    main()
