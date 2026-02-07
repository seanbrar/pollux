# Cookbook

Scenario-first recipes for Pollux that are designed to be runnable, teachable, and production-minded.

## Recipe quality bar

Every recipe in this cookbook should meet this contract:

- **Problem-first:** states when to use and when not to use the pattern.
- **Runnable:** commands work from repo root with `python -m cookbook ...`.
- **Interpretable:** page explains what healthy output looks like.
- **Operational:** includes failure modes and concrete tuning levers.
- **Extensible:** ends with practical follow-on experiments.

## Recommended workflow

1. Start in `--mock` mode (default) to validate flow and args.
2. Switch to `--no-mock` when prompts and inputs are stable.
3. Scale file counts/concurrency incrementally and observe metrics.

## Learning paths

### Path A: First successful runs

1. [Analyze Single Paper](getting-started/analyze-single-paper.md)
2. [Broadcast Process Files](getting-started/broadcast-process-files.md)
3. [Comparative Analysis](research-workflows/comparative-analysis.md)

### Path B: Efficiency and scale

1. [Context Caching Explicit](optimization/context-caching-explicit.md)
2. [Cache Warming and TTL](optimization/cache-warming-and-ttl.md)
3. [Large-Scale Fan-Out](optimization/large-scale-fan-out.md)

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

Seed demo inputs for deterministic runs:

```bash
make demo-data
```

