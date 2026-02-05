# Pollux Cookbook

Practical, problem-first recipes for multimodal batch analysis with Pollux.

## Philosophy

Each recipe is designed to be:

- **Runnable**: one command from the repo root.
- **Teachable**: scenario-first framing, not just API calls.
- **Production-minded**: shows operational patterns, not toy snippets.

## Quick Start

```bash
# 1) List recipes
python -m cookbook --list

# 2) Run the baseline recipe in mock mode (default)
python -m cookbook getting-started/analyze-single-paper -- --input path/to/file.pdf

# 3) Run against a real provider
python -m cookbook getting-started/analyze-single-paper -- \
  --input path/to/file.pdf --no-mock --provider gemini --model gemini-2.5-flash-lite
```

Notes:

- Pass recipe-specific flags after `--`.
- Use `make demo-data` for local sample inputs.
- Most recipes support `--mock/--no-mock`, `--provider`, and `--model`.

## Recipe Catalog

### Getting Started

| Recipe | Focus |
| --- | --- |
| `analyze-single-paper.py` | Single-source baseline and output inspection |
| `batch-process-files.py` | Multi-file processing with shared prompts |
| `extract-video-insights.py` | Video analysis basics |

### Optimization

| Recipe | Focus |
| --- | --- |
| `cache-warming-and-ttl.py` | Warm/reuse cache and compare usage |
| `context-caching-explicit.py` | Explicit cache workflow |
| `large-scale-batching.py` | Bounded client-side concurrency |

### Research Workflows

| Recipe | Focus |
| --- | --- |
| `comparative-analysis.py` | Structured source-to-source comparison |
| `multi-video-batch.py` | Cross-video synthesis |

### Production

| Recipe | Focus |
| --- | --- |
| `rate-limits-and-concurrency.py` | Throughput controls and concurrency tuning |
| `resume-on-failure.py` | Durable manifest + retry/resume pattern |

### Templates

| Template | Purpose |
| --- | --- |
| `recipe-template.py` | Starting point for new recipes |
| `custom-schema-template.py` | Schema-first extraction flow |

## Troubleshooting

- **No demo files**: run `make demo-data` or provide `--input`.
- **API auth errors**: set `GEMINI_API_KEY`/`OPENAI_API_KEY`, then use `--no-mock`.
- **Rate limits**: lower concurrency and retry with smaller `--limit` values.
