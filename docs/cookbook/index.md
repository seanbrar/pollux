# Cookbook

Scenario-first recipes for Pollux that are designed to be runnable, teachable, and production-minded.

## Setup

Recipes require a one-time dev install so that `import pollux` works:

```bash
uv sync --all-extras          # or: pip install -e ".[dev]"
```

Verify the install:

```bash
python -m cookbook --list
```

Tip: if `python` isn’t on your PATH, use one of:

- `python3 -m cookbook --list`
- `uv run python -m cookbook --list`

Then seed demo inputs for deterministic runs:

```bash
make demo-data
```

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
3. [Structured Output Extraction](getting-started/structured-output-extraction.md)
4. [Comparative Analysis](research-workflows/comparative-analysis.md)

### Path B: Efficiency and scale

1. [Run vs RunMany](optimization/run-vs-run-many.md)
2. [Cache Warming and TTL](optimization/cache-warming-and-ttl.md)
3. [Large-Scale Fan-Out](optimization/large-scale-fan-out.md)

### Path C: Production hardening

1. [Rate Limits and Concurrency](production/rate-limits-and-concurrency.md)
2. [Resume on Failure](production/resume-on-failure.md)

## Recipe catalog

### Getting started

| Recipe | Focus |
| --- | --- |
| [Analyze Single Paper](getting-started/analyze-single-paper.md) | Single-source baseline and output inspection |
| [Broadcast Process Files](getting-started/broadcast-process-files.md) | Multi-file processing with shared prompts |
| [Structured Output Extraction](getting-started/structured-output-extraction.md) | Schema-first extraction (typed structured output) |
| [Extract Media Insights](getting-started/extract-media-insights.md) | Single image/audio/video analysis baseline |

### Optimization

| Recipe | Focus |
| --- | --- |
| [Cache Warming and TTL](optimization/cache-warming-and-ttl.md) | Warm/reuse cache and compare usage |
| [Large-Scale Fan-Out](optimization/large-scale-fan-out.md) | Bounded client-side concurrency |
| [Run vs RunMany](optimization/run-vs-run-many.md) | Prompt batching and API overhead comparison |

### Research workflows

| Recipe | Focus |
| --- | --- |
| [Comparative Analysis](research-workflows/comparative-analysis.md) | Structured source-to-source comparison |
| [Multi-Video Synthesis](research-workflows/multi-video-synthesis.md) | Cross-video synthesis |

### Production

| Recipe | Focus |
| --- | --- |
| [Rate Limits and Concurrency](production/rate-limits-and-concurrency.md) | Throughput controls and concurrency tuning |
| [Resume on Failure](production/resume-on-failure.md) | Durable manifest + retry/resume pattern |

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

## Troubleshooting

- **No demo files:** run `make demo-data` or provide explicit `--input` paths.
- **Import errors:** run `uv sync --all-extras` (or editable install) so `import pollux` resolves.
- **API auth errors:** set `GEMINI_API_KEY`/`OPENAI_API_KEY`, then use `--no-mock`.
- **Rate limits:** lower concurrency, reduce prompt counts, and stage workload size with `--limit`.
