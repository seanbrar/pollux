# Pollux Cookbook

Practical, problem-first recipes for multimodal analysis with Pollux.

## Quality standard

Every recipe should be:

- **Runnable:** one command from the repo root.
- **Teachable:** explains success signals and failure modes.
- **Operational:** shows tuning levers for reliability and cost.
- **Extensible:** points to concrete next experiments.

## Setup

Recipes require a dev install so that `import pollux` resolves through the package manager:

```bash
uv sync --all-extras          # or: pip install -e ".[dev]"
```

Then seed demo inputs:

```bash
make demo-data
```

## Quick Start

```bash
# 1) List recipes
python -m cookbook --list

# 2) Run a baseline recipe in mock mode (default)
python -m cookbook getting-started/analyze-single-paper \
  --input cookbook/data/demo/text-medium/input.txt

# 3) Run against a real provider
python -m cookbook getting-started/analyze-single-paper \
  --input path/to/file.pdf --no-mock --provider gemini --model gemini-2.5-flash-lite
```

Notes:

- Use `make demo-data` for local sample inputs.
- Most recipes support `--mock/--no-mock`, `--provider`, and `--model`.

## Recipe Catalog

### Getting Started

| Recipe | Focus |
| --- | --- |
| `analyze-single-paper.py` | Single-source baseline and output inspection |
| `broadcast-process-files.py` | Multi-file processing with shared prompts |
| `structured-output-extraction.py` | Schema-first extraction (typed structured output) |
| `extract-media-insights.py` | Single-image/audio/video analysis baseline |

### Optimization

| Recipe | Focus |
| --- | --- |
| `cache-warming-and-ttl.py` | Warm/reuse cache and compare usage |
| `large-scale-fan-out.py` | Bounded client-side concurrency |
| `run-vs-run-many.py` | Prompt batching and API overhead comparison |

### Research Workflows

| Recipe | Focus |
| --- | --- |
| `comparative-analysis.py` | Structured source-to-source comparison |
| `multi-video-synthesis.py` | Cross-video synthesis |

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

- **No demo files:** run `make demo-data` or provide explicit input paths.
- **API auth errors:** set `GEMINI_API_KEY`/`OPENAI_API_KEY`, then use `--no-mock`.
- **Rate limits:** lower concurrency and stage workload size with `--limit`.
