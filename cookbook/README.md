# Pollux Cookbook

Problem-first recipes for real-world multimodal batch analysis.

## Quick Start

```bash
# List available recipes
python -m cookbook --list

# Run a recipe
python -m cookbook getting-started/analyze-single-paper -- --limit 1
```

**Notes:**

- Pass recipe flags after `--`
- Many recipes accept `--input` (file or directory) and `--limit`
- Demo data: `make demo-data` (optional)

## Recipes

### Getting Started

| Recipe | What it does |
|--------|--------------|
| `analyze-single-paper.py` | Extract insights from a single file |
| `batch-process-files.py` | Process multiple documents at once |
| `conversation-follow-ups.py` | Multi-turn conversations with persistence |
| `extract-video-insights.py` | Pull highlights from video content |

### Optimization

| Recipe | What it does |
|--------|--------------|
| `cache-warming-and-ttl.py` | Warm caches with deterministic keys |
| `context-caching-explicit.py` | Explicit cache create/reuse |
| `large-scale-batching.py` | Fan-out with bounded concurrency |

### Research Workflows

| Recipe | What it does |
|--------|--------------|
| `comparative-analysis.py` | Compare sources side-by-side |
| `multi-video-batch.py` | Compare/summarize across videos |

### Production

| Recipe | What it does |
|--------|--------------|
| `rate-limits-and-concurrency.py` | Tier config and concurrency behavior |
| `resume-on-failure.py` | Persist state, retry failed items |

### Templates

| Template | What it does |
|----------|--------------|
| `recipe-template.py` | Boilerplate for new recipes |
| `custom-schema-template.py` | Schema-first extraction |

## Configuration

Mock mode is default. For real API calls:

```bash
export GEMINI_API_KEY=...
export POLLUX_TIER=tier_1
export POLLUX_USE_REAL_API=true
```

## Troubleshooting

- **No demo data**: Run `make demo-data` or use `--input /path/to/files`
- **429s / throttling**: Set `POLLUX_TIER` to match your billing tier
- **Slow runs**: Start with small text files before large PDFs/videos
