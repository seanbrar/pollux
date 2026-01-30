# Pollux Cookbook

Problem-first recipes for real-world, multimodal batch analysis with Pollux.

If you want a quick win, start here:

- `getting-started/analyze-single-paper.py`
- `getting-started/batch-process-files.py`
- `getting-started/structured-json-robust.py`

## Run a recipe

From the repo root:

```bash
python -m cookbook --list
python -m cookbook getting-started/analyze-single-paper -- --limit 1
```

Notes:

- Use the dotted form for portability: `python -m cookbook getting_started.analyze_single_paper`
- Pass recipe flags after `--`.
- Many recipes accept `--input` (file or directory) and `--limit`.

## Demo data (optional)

```bash
make demo-data
```

By default, recipes look for demo data under `cookbook/data/demo/text-medium/`.
Provide your own files with `--input`.

## Configure the real API (optional)

Mock mode is default. For real API calls:

```bash
export GEMINI_API_KEY=...
export POLLUX_TIER=tier_1
export POLLUX_USE_REAL_API=true
```

## Recipes by category

### Getting started (fast wins)

| Recipe | When you need to... | Difficulty | Time |
|--------|-------------------|------------|------|
| `getting-started/analyze-single-paper.py` | Extract insights from one file | 1/5 | ~5 min |
| `getting-started/batch-process-files.py` | Process multiple documents | 2/5 | ~8 min |
| `getting-started/extract-video-insights.py` | Pull highlights from a video | 2/5 | ~8 min |
| `getting-started/token-estimate-preview.py` | Estimate tokens/cost before running | 2/5 | ~5-8 min |
| `getting-started/structured-json-robust.py` | Get JSON with schema + fallbacks | 2/5 | ~8-10 min |
| `getting-started/youtube-qa-timestamps.py` | Q&A on YouTube with timestamps | 2/5 | ~8 min |
| `getting-started/conversation-follow-ups.py` | Persisted follow-ups via ConversationEngine | 2/5 | ~8-10 min |

### Research workflows

- `research-workflows/literature-synthesis.py` - Synthesize findings across many papers
- `research-workflows/comparative-analysis.py` - Compare sources side-by-side
- `research-workflows/content-assessment.py` - Assess course/lecture materials
- `research-workflows/fact-table-extraction.py` - Extract normalized facts to JSONL/CSV
- `research-workflows/multi-video-batch.py` - Compare/summarize across videos
- `research-workflows/system-instructions-with-research-helper.py` - Apply system instructions while benchmarking efficiency

### Optimization (cost, scale, speed)

- `optimization/cache-warming-and-ttl.py` - Warm caches with deterministic keys and TTL
- `optimization/chunking-large-docs.py` - Chunk large docs and merge answers
- `optimization/large-scale-batching.py` - Fan-out across sources with bounded concurrency
- `optimization/multi-format-pipeline.py` - Analyze mixed media together
- `optimization/context-caching-explicit.py` - Explicit cache create/reuse and token savings
- `optimization/long-transcript-chunking.py` - Token-aware transcript chunking + stitching
- `optimization/efficiency-comparison.py` - Compare vectorized vs naive for N prompts

### Production patterns

- `production/monitoring-telemetry.py` - Inspect per-stage timings and metrics
- `production/resume-on-failure.py` - Persist state and rerun only failed items
- `production/custom-integrations.py` - Attach a custom telemetry reporter
- `production/rate-limits-and-concurrency.py` - Tier config + bounded concurrency behavior

### Templates

- `templates/recipe-template.py` - Boilerplate for a new recipe
- `templates/custom-schema-template.py` - Schema-first extraction template

## Troubleshooting

- No demo data: run `make demo-data` or pass `--input /path/to/files`.
- 429s / throttling: set `POLLUX_TIER` to match your billing tier; reduce `--limit`.
- Slow runs: start with small text files before large PDFs/videos.
