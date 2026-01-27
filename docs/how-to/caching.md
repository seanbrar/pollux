# Caching with the Command Pipeline

Last reviewed: 2025-09

Goal: Enable and reuse provider-side caches for shared context to reduce token usage and latency on repeated calls. This page shows minimal, copy‑paste steps and how to verify reuse.

When to use: You run the same shared context (system instruction + shared parts) repeatedly across prompts and want predictable reuse.

Prerequisites

- Python 3.13; repository installed (`make install-dev`).
- Default is mock mode (no real provider). For actual cache creation/reuse, enable real API and set your billing tier: `GEMINI_API_KEY`, `POLLUX_USE_REAL_API=1`, `POLLUX_TIER=...`.

## 1) Minimal: create and reuse a cache (two runs)

This example runs a tiny batch twice with the same deterministic cache key. In mock mode it’s a no‑op (still succeeds). With real API, the second run should apply the cache.

```python title="cache_min.py"
import asyncio
from pollux import types
from pollux.frontdoor import run_batch
from pollux.core.execution_options import ExecutionOptions, CacheOptions

async def main() -> None:
    # Shared context (shaped by prompts + sources)
    prompts = [
        "Summarize in one sentence.",
        "List 3 keywords.",
    ]
    sources = [types.Source.from_text("Caching demo: shared context text")]

    # Choose a deterministic cache identity; TTL optional
    cache_key = "demo.shared.context.v1"
    opts = ExecutionOptions(
        cache=CacheOptions(deterministic_key=cache_key, ttl_seconds=3600)
    )

    # First run (creates cache when real API & provider supports caches)
    first = await run_batch(prompts=prompts, sources=sources, options=opts)
    print("first:", first["status"], first.get("usage", {}))

    # Second run (reuses cache when real API)
    second = await run_batch(prompts=prompts, sources=sources, options=opts)
    print("second:", second["status"], second.get("usage", {}))

    # Simple success in all modes
    assert first["status"] == "ok" and second["status"] == "ok"

    # Optional: verification when real API is enabled
    metrics = second.get("metrics", {}) if isinstance(second, dict) else {}
    if metrics:
        # Expect application recorded at execution time
        print("cache_application:", metrics.get("cache_application"))
        # Some providers expose per-prompt usage including cached counters
        per_prompt = metrics.get("per_prompt") or []
        if per_prompt:
            cached = sum(int(u.get("cached_content_token_count", 0) or 0) for u in per_prompt)
            print("cached_content_token_count (sum):", cached)

asyncio.run(main())
```

Expected

- Mock mode: both runs print `ok`; metrics are minimal. Caching is a no‑op without a real provider adapter.
- Real API: the second run includes `metrics.cache_application == "plan"` and may show `cached_content_token_count > 0` in `metrics.per_prompt[*].usage` when provided by the SDK.

## 2) Policy knobs

Use `ExecutionOptions.cache_policy` for conservative, planner‑scoped controls:

```python
from pollux.core.execution_options import CachePolicyHint, make_execution_options

opts = make_execution_options(
    cache_policy=CachePolicyHint(
        first_turn_only=True,   # default: only create on first turn
        respect_floor=True,     # default: apply provider floor when confident
        conf_skip_floor=0.85,   # default confidence threshold
    )
)
```

Notes

- Deterministic cache identity: if you omit `CacheOptions`, the system computes a stable key from model + system + shared parts.
- TTL: pass `ttl_seconds` in `CacheOptions` to bound cache lifetime (provider supported).
- Reuse only: set `reuse_only=True` to avoid creating a cache when it doesn’t already exist.
- Concurrency: cache creation is bounded and de‑duplicated within a plan; repeated URIs/downloads are single‑flight where applicable.

## 3) Troubleshooting

- No cache effects: ensure real API is enabled and the provider supports caching (`enable_caching` and `ttl_seconds` are passed via provider adapter). Mock mode won’t create caches.
- Missing counters: not all SDKs expose `cached_*` usage; rely on `metrics.cache_application` to confirm reuse.
- Large files: inline caching payloads skip very large files by design (see Reference → Caching for size threshold).

See also

- Explanation → Concepts → [Command Pipeline](../explanation/concepts/command-pipeline.md)
- Reference → [Caching](../reference/caching.md)
