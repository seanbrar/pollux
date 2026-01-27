# Research Utilities

Lightweight helpers for benchmarking and exploratory analysis that live off the core public surface. Intended for advanced users who want to compare vectorized batching vs naive per‑prompt execution and inspect timing/usage characteristics.

Status: pre‑1.0 (not part of the stable public API; surface may change until first stable release).

## Prerequisites

- Python 3.13 and an installed package or editable repo checkout:
  - From repo root: `pip install -e .[dev]`
- Environment: set secrets and tier in `.env` or your shell:
  - `GEMINI_API_KEY=...`
  - Optional: `POLLUX_TIER=free|tier_1|tier_2|tier_3`
- Data: a small test corpus, e.g. `examples/test_data/research_papers/` (included). Replace with your own directory if preferred.

## Quickstart

```python
import asyncio
from pollux import research, types

async def main():
    prompts = [
        "Summarize core efficiency ideas",
        "List three concrete optimization methods",
    ]
    # Use a small local corpus; adjust as needed
    sources = types.sources_from_directory("examples/test_data/research_papers/")

    report = await research.compare_efficiency(
        prompts,
        sources,
        include_pipeline_durations=True,
        trials=1,           # increase for more stable stats
        warmup=0,           # warm-up iterations, if desired
        ensure_uncached=False,  # set True to avoid cache effects
        label="local-demo",
    )

    print(report.summary(verbose=False, ascii_only=True))
    data = report.to_dict()
    print({
        "ratios": data["ratios"],
        "savings": data["savings"],
        "env": {
            "vec_concurrency_effective": data["env"]["vec_concurrency_effective"],
            "naive_concurrency_effective": data["env"]["naive_concurrency_effective"],
        },
    })

asyncio.run(main())
```

### Aggregate mode (optional)

For token‑economics comparisons when multiple prompts share the same context, you can aggregate them into one provider call. Prefer structured output for robust parsing:

```python
report = await research.compare_efficiency(
    prompts,
    sources,
    mode="aggregate",
    prefer_json=True,       # encourages a JSON array of answers
)
```

When the effective mode is aggregate and `prefer_json` is not provided, the helper implicitly enables JSON preference for more robust parsing. The effective value is recorded in `data["env"]["prefer_json_effective"]`.

## Validate Results

- The `summary()` line reports ratios where values > 1 indicate the vectorized path used fewer tokens/less time/fewer calls than the naive baseline (ratios are computed as `baseline / vectorized`). Example output shape (values will vary):

  ```text
  tokens x1.23 (saved 118), time x1.41 (saved 2.315s), calls x3.00 (saved 6) (prompts=2, sources=10, reqs: vec=4, naive=12) [mode=aggregate]
  ```

- The `to_dict()` payload includes structured fields you can persist for later analysis:

  ```python
  data = report.to_dict()
  assert "ratios" in data and "savings" in data and "env" in data
  # Example shapes
  assert set(data["ratios"]).issuperset({"tokens", "time", "calls"})
  assert set(data["savings"]).issuperset({"tokens", "time_s", "calls"})
  assert set(data["env"]).issuperset({"vec_concurrency_effective", "naive_concurrency_effective"})
  assert data.get("vec_mode") in {"batch", "aggregate"}
  ```

## What it does

- Compares two paths over the same workload:
  - Vectorized batching (`run_batch(prompts, sources)`) once
  - Naive baseline: one call per prompt (optionally parallelized)
- Returns an `EfficiencyReport` with:
  - Aggregates: tokens, time, request counts (both paths)
  - Ratios: `tokens`, `time`, and `calls` (> 1 means vectorized better; < 1 worse)
  - Optional distributions: pipeline and per‑call durations
  - Trial stats when `trials > 1` (mean, p95)
  - Best‑effort environment capture for reproducibility

## Key parameters

- `concurrency`: vectorized path fan‑out bound (client‑side)
- `naive_concurrency`: per‑prompt baseline fan‑out (defaults to parity)
- `trials` / `warmup`: collect multiple observations and optional warm‑ups
- `include_pipeline_durations`: include pipeline and per‑call duration views
- `ensure_uncached`: force caching off via config override for unbiased timing
- `mode`: vectorized execution shape
  - `"auto"` (default): choose aggregate when there are multiple prompts, else batch
  - `"batch"`: pass prompts independently to the pipeline
  - `"aggregate"`: join prompts into one instruction; ask for a JSON array of answers
  - Tip: for `"aggregate"`, `prefer_json` defaults to True when not provided; set explicitly to override
- `aggregate_prompt_builder`: optional callable to customize the aggregate instruction text
- `label`: free‑form tag attached to the report

For the full API and dataclass fields, see the function and class reference in the code docstrings (`research.compare_efficiency`, `research.EfficiencyReport`).

## When to use aggregate vs batch

- Use `mode="aggregate"` when:
  - Many prompts share the same `sources` (large shared context dominates input tokens).
  - You want to minimize provider calls and re‑processing of shared context.
  - You can accept a single call that returns a JSON array of answers (order matches `prompts`).
  - You control prompts well enough to enforce a compact, structured multi‑answer output (set `prefer_json=True`).
- Prefer `mode="batch"` when:
  - Prompts require independent handling (different templates or different sources per prompt).
  - You need per‑prompt request metrics, partial failures, or per‑prompt streaming/telemetry.
  - Outputs are lengthy/unbounded or the model struggles to reliably answer multiple questions in one go.
- Consider `mode="auto"` for quick studies (default):
  - Aggregates automatically when there are multiple prompts; behaves like `"batch"` for a single prompt.
  - Good for exploratory token‑economics comparisons; switch to an explicit mode once you pick a shape.
- Caveats for `aggregate`:
  - A single failure affects the whole vectorized call; naive baseline still runs per prompt.
  - Per‑prompt pipeline detail is limited to what the pipeline surfaces in `metrics`.
  - Ensure answers align with prompt order and count; prefer numbered prompts to reduce ambiguity.
  - When `prefer_json` is omitted, the helper sets it to True and records this as `env.prefer_json_effective=True`.

## Notes

- Requires a configured API key (`GEMINI_API_KEY`) and valid sources.
- Ratios are computed as `baseline / vectorized` and may be `inf` when the
  vectorized path uses zero of a quantity (rare for time, possible for tokens in
  degenerate cases).
  - For very small workloads, fixed overhead can make ratios ≤ 1; increase
    prompts or trials to surface vectorization benefits.
- This module is intentionally separate to avoid expanding the top‑level API.

## Safety

- Benchmarks may incur API costs and hit rate limits. Start with small corpora and `trials=1`, `warmup=0`.
- Set `POLLUX_TIER` to match your billing tier to avoid throttling.
- `ensure_uncached=True` disables caching and increases request volume; use only when you need uncached timing.
- Telemetry can be enabled/disabled via configuration; ensure sensitive data policies are respected in your environment.

## See also

- How‑to: configuration and setup — `docs/SETUP.md`, `docs/reference/configuration.md`
- Example script: `examples/research_efficiency_demo.py` (kept up‑to‑date; prefer this for runnable demos)
- Concept/decision: vectorization and fan‑out — `docs/explanation/decisions/RFP-0001-batch-vectorization-and-fanout.md`
- Usage/metrics examples with `run_batch` — `docs/metrics.md`, `docs/how-to/remote-file-materialization.md`

## Limitations

- Best‑effort research helper; numbers depend on inputs, provider tier, and system load. Not a marketing benchmark.
- Surface is pre‑1.0 and may change; reference the code docstrings for the authoritative API and field names.

## Environment capture

The report includes a lightweight runtime context under `data["env"]` to aid reproducibility and cross‑machine comparisons:

- version: installed package version
- python_version, python_impl: interpreter details
- platform, os_name: OS/platform summary
- cpu_count, pid: host/process hints
- git_sha, git_dirty: read from `GIT_SHA`/`GITHUB_SHA` and `GIT_DIRTY` env vars if provided (no shelling out)

These are best‑effort and may be `None` when not available.

Additional notes:

- Effective settings: when aggregating and `prefer_json` is not provided, the helper implicitly enables JSON preference. Inspect `data["env"]["prefer_json_effective"]`.
- Sanity checks: in aggregate mode, the helper records the expected and observed answer counts (`aggregate_expected_answer_count`, `aggregate_observed_answer_count`) when available.
