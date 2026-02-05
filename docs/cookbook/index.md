# Cookbook

Scenario-first recipes for Pollux, written to be run and adapted in real projects.

## What makes these recipes "gold standard"

- **Problem-first:** each recipe starts with a concrete operational need.
- **Runnable:** command examples work from the repo root.
- **Interpretable:** each page tells you what "good" output looks like.
- **Extensible:** every recipe ends with practical next experiments.

## Recommended workflow

1. Start in `--mock` mode (default) to validate flow and CLI args.
2. Move to `--no-mock` when your input/prompt looks right.
3. Scale up file counts, concurrency, and complexity gradually.

## Learning paths

### Path A: First successful runs

1. [Analyze Single Paper](getting-started/analyze-single-paper.md)
2. [Batch Process Files](getting-started/batch-process-files.md)
3. [Comparative Analysis](research-workflows/comparative-analysis.md)

### Path B: Efficiency and scale

1. [Context Caching Explicit](optimization/context-caching-explicit.md)
2. [Cache Warming and TTL](optimization/cache-warming-and-ttl.md)
3. [Large-Scale Batching](optimization/large-scale-batching.md)

### Path C: Production hardening

1. [Rate Limits and Concurrency](production/rate-limits-and-concurrency.md)
2. [Resume on Failure](production/resume-on-failure.md)

## Runtime conventions

All recipes support:

- `--mock/--no-mock` (default: `--mock`)
- `--provider {gemini,openai}`
- `--model <model-id>`
- `--api-key <key>` (optional override)

Catalog:

```bash
python -m cookbook --list
```

## Input setup

Use demo inputs for a fast start:

```bash
make demo-data
```

Then pass `--input` explicitly for deterministic runs.
