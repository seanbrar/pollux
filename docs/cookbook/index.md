# Cookbook

Scenario-driven recipes for Pollux — runnable, teachable, and
production-minded.

## Setup

```bash
uv sync --all-extras          # installs all dev/test/docs/lint deps
python -m cookbook --list      # verify install
make demo-data                # seed demo inputs
```

## Recipe Catalog

| Recipe | Focus |
|---|---|
| [Analyze Single Paper](getting-started/analyze-single-paper.md) | Single-source baseline and output inspection |
| [Broadcast Process Files](getting-started/broadcast-process-files.md) | Multi-file processing with shared prompts |
| [Structured Output Extraction](getting-started/structured-output-extraction.md) | Schema-first typed extraction |
| [Extract Media Insights](getting-started/extract-media-insights.md) | Image/audio/video analysis baseline |
| [Run vs RunMany](optimization/run-vs-run-many.md) | Prompt batching and overhead comparison |
| [Cache Warming and TTL](optimization/cache-warming-and-ttl.md) | Cache impact and TTL tuning |
| [Large-Scale Fan-Out](optimization/large-scale-fan-out.md) | Bounded client-side concurrency |
| [Comparative Analysis](research-workflows/comparative-analysis.md) | Structured source-to-source comparison |
| [Multi-Video Synthesis](research-workflows/multi-video-synthesis.md) | Cross-video synthesis |
| [Rate Limits and Concurrency](production/rate-limits-and-concurrency.md) | Throughput controls and concurrency tuning |
| [Resume on Failure](production/resume-on-failure.md) | Durable manifest + retry/resume |

## Learning Paths

**First successful runs:** Analyze Single Paper → Broadcast Process Files →
Structured Output → Comparative Analysis

**Efficiency and scale:** Run vs RunMany → Cache Warming → Large-Scale Fan-Out

**Production hardening:** Rate Limits and Concurrency → Resume on Failure

## Runtime Conventions

All recipes support these flags:

- `--mock / --no-mock` (default: `--mock`)
- `--provider {gemini,openai}`
- `--model <model-id>`
- `--api-key <key>` (optional override)

Recommended workflow: start in `--mock` to validate flow, switch to
`--no-mock` when prompts are stable, then scale incrementally.

## Troubleshooting

- **No demo files:** run `make demo-data` or provide explicit `--input` paths.
- **Import errors:** run `uv sync --all-extras` so `import pollux` resolves.
- **API auth errors:** set `GEMINI_API_KEY`/`OPENAI_API_KEY`, then use `--no-mock`.
- **Rate limits:** lower concurrency and stage workload size with `--limit`.
