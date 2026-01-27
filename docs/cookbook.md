# Cookbook — Practical Recipes

Problem‑first, copy‑pasteable recipes you can run directly from the repo with the built‑in runner.

## Runner Overview

- Command: `python -m cookbook [--cwd-repo-root|--no-cwd-repo-root] [--list] <spec> [-- recipe_args]`
- List recipes: `python -m cookbook --list`
- Spec forms:
  - Path relative to repo: `cookbook/production/resume-on-failure.py`
  - Path relative to `cookbook/`: `production/resume-on-failure.py`
  - Dotted (maps `_` → `-` on disk): `production.resume_on_failure`
- Working directory: defaults to repository root. Opt out with `--no-cwd-repo-root` if you want to run from the current directory.
- Passing args: place recipe flags after `--` (everything after is forwarded to the recipe).

For more details about the runner and `pollux-config`, see Reference → CLI: reference/cli.md.

Examples:

```bash
# List available recipes
python -m cookbook --list

# Run via path and pass recipe args
python -m cookbook optimization/context-caching-explicit -- --limit 2

# Run via dotted spec
python -m cookbook production.resume_on_failure -- --limit 1
```

Notes:

- For real API calls, set `GEMINI_API_KEY`, `POLLUX_TIER`, and `POLLUX_USE_REAL_API=1`.
- If you prefer mock mode (default), no key is needed; outputs include the `echo:` prefix.

!!! warning "Costs & rate limits"
    Real API calls may incur costs and are subject to tier‑specific rate limits. Set `POLLUX_TIER` to match your billing plan and start with low concurrency.

## Demo Data (optional)

Several recipes expect local demo inputs. Seed them on demand:

```bash
make demo-data            # defaults: TEXT=medium, MEDIA=basic
# variants
make demo-data TEXT=full
make demo-data MEDIA=none
```

Clean up:

```bash
make clean-demo-data
```

No `make` available? Use the Python helper directly:

```bash
python scripts/demo_data.py --text medium        # default
python scripts/demo_data.py --text full
python scripts/demo_data.py --text medium --media basic
```

## Highlights

- Getting started:
  - Analyze one file: `getting-started/analyze-single-paper.py`
  - Batch process directory: `getting-started/batch-process-files.py`
  - Token estimate preview: `getting-started/token-estimate-preview.py`
  - Structured JSON with fallbacks: `getting-started/structured-json-robust.py`
  - YouTube Q&A with timestamps: `getting-started/youtube-qa-timestamps.py`
  - Conversation follow-ups: `getting-started/conversation-follow-ups.py`

- Optimization:
  - Cache warming with TTL: `optimization/cache-warming-and-ttl.py`
  - Chunking large docs: `optimization/chunking-large-docs.py`
  - Large-scale batching: `optimization/large-scale-batching.py`
  - Multi-format pipeline: `optimization/multi-format-pipeline.py`
  - Explicit cache create/reuse: `optimization/context-caching-explicit.py`

- Production patterns:
  - Resume on failure: `production/resume-on-failure.py`
  - Monitoring + telemetry: `production/monitoring-telemetry.py`
  - Rate limits + concurrency: `production/rate-limits-and-concurrency.py`
  - Custom integrations: `production/custom-integrations.py`

- Research workflows:
  - Comparative analysis: `research-workflows/comparative-analysis.py`
  - Fact table extraction: `research-workflows/fact-table-extraction.py`
  - Literature synthesis: `research-workflows/literature-synthesis.py`
  - Multi‑video batch: `research-workflows/multi-video-batch.py`
  - Content assessment: `research-workflows/content-assessment.py`
  - System instructions helper: `research-workflows/system-instructions-with-research-helper.py`

Browse all recipes: <https://github.com/seanbrar/gemini-batch-prediction/tree/main/cookbook>

See also:

- Tutorials → [Quickstart](tutorials/quickstart.md) and [First Batch](tutorials/first-batch.md)
- How‑to → [Configuration](how-to/configuration.md), [Verify Real API](how-to/verify-real-api.md), [Troubleshooting](how-to/troubleshooting.md)
- Domains → [Research Overview](domains/research.md)

Last reviewed: 2025-09
