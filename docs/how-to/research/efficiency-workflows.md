# Research: Efficiency Workflows

Last reviewed: 2025-09

Purpose: Task‑focused steps to run efficiency experiments and analyze results using the research module.

Prerequisites

- Python 3.13; repository installed (`make install-dev`).
- Default is mock mode. For real API, set `GEMINI_API_KEY` and `POLLUX_USE_REAL_API=1`, and match `POLLUX_TIER` to your billing to avoid throttling.

## 1) Minimal, reproducible run

This example compares vectorized batching to a naive per‑prompt baseline over a tiny workload.

```python title="compare_efficiency_min.py"
from pollux import types, frontdoor
from pollux.research import compare_efficiency

# Small corpus: two prompts across two sources
prompts = [
    "Summarize in one sentence.",
    "List 3 keywords.",
]

sources = [
    types.Source.from_text("Batching improves throughput and reduces overhead."),
    types.Source.from_text("Vectorization can reduce token usage via shared context."),
]

report = compare_efficiency(
    prompts=prompts,
    sources=sources,
    mode="auto",          # try vectorized forms when advantageous
    trials=1,              # start small to control cost/time
)

print("ratio_tokens:", report.ratios.tokens)
print("ratio_time:", report.ratios.time)
print("calls_baseline:", report.baseline.calls)
print("calls_vectorized:", report.vectorized.calls)

# Simple success checks for automation
assert report.baseline.calls >= report.vectorized.calls
```

Expected

- In mock mode, ratios are deterministic placeholders with `status == "ok"`.
- With real API, ratios reflect actual usage and timing. Values < 1.0 suggest gains from vectorization.

## 2) Options and tips

- Modes: `mode="auto"` (default), `"batch"`, or `"aggregate"` (prefers JSON for multi‑answer parsing).
- Start small: `trials=1` and a tiny corpus; scale up gradually.
- If you must avoid cached results for repeatability, set `ensure_uncached=True` (may increase request volume/cost).
- Monitor rate limits: reduce concurrency or raise backoffs if throttled; see How‑to → [Configuration](../../how-to/configuration.md).

## Troubleshooting

- Missing key: set `GEMINI_API_KEY` and re‑run. Use `pollux-config doctor` to verify readiness.
- Timeouts/rate limits: match `POLLUX_TIER` to billing; reduce concurrency.
- Non‑JSON aggregates: prefer `mode="aggregate"` only when your prompts return parseable structures.

See also

- Reference → API → [Research Utilities](../../reference/api/research.md)
- Domains → [Research](../../domains/research.md)
- Reference → [Research Catalog](../../reference/research/catalog.md)
