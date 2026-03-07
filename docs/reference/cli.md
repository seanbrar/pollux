# CLI - Cookbook Runner

Use cookbook recipes when you want a full runnable script you can execute,
inspect, and modify. The docs pages teach Pollux concepts and boundaries; the
cookbook gives you end-to-end starting points that apply those concepts in
real workflows.

Pollux currently ships one documented CLI surface:

- `python -m cookbook`: run recipes under `cookbook/` without manual `PYTHONPATH` setup.

## How Recipes Fit the Docs

- Read the topical docs when you need to understand a concept, boundary, or API shape.
- Run a cookbook recipe when you want a complete script with CLI flags, mock mode, and inspectable output.
- Treat recipes as forkable starting points, not as the only place a concept is explained.

## Prerequisites

Install dev dependencies so recipe imports resolve correctly:

```bash
uv sync --all-extras          # installs all dev/test/docs/lint deps
```

## Command Shape

```bash
python -m cookbook [--list] [--cwd-repo-root|--no-cwd-repo-root] [<spec>] [recipe_args...]
```

- `--list`: list available recipes and exit.
- `<spec>`: recipe identifier to run.
- `recipe_args...`: args forwarded to the selected recipe.
- `--cwd-repo-root` (default): run recipes from repo root.
- `--no-cwd-repo-root`: keep current working directory.

If you include `--`, everything after it is forwarded to the recipe unchanged.

## Spec Forms

The runner accepts several equivalent recipe spec forms:

- Repo-relative path: `cookbook/production/resume-on-failure.py`
- Cookbook-relative path: `production/resume-on-failure.py`
- Dotted form (`_` maps to `-`): `production.resume_on_failure`

## Common Commands

```bash
# List recipes
python -m cookbook --list

# Bare invocation prints a welcome message and quick-start commands
python -m cookbook

# Run by cookbook-relative path
python -m cookbook optimization/cache-warming-and-ttl --limit 2 --ttl 3600

# Run a project recipe
python -m cookbook projects/paper-to-workshop-kit --input path/to/paper.pdf

# Run by dotted spec
python -m cookbook production.resume_on_failure --limit 1

# Explicit passthrough separator
python -m cookbook getting-started/analyze-single-paper -- --help
```

## Recipe Help

The runner forwards `--help` to a recipe when a valid recipe spec comes first:

```bash
python -m cookbook getting-started/analyze-single-paper --help
```

## Cross-Platform Notes

=== "Bash/Zsh (macOS/Linux)"

```bash
python -m cookbook --list
python -m cookbook optimization/cache-warming-and-ttl --limit 2 --ttl 3600
python -m cookbook production.resume_on_failure --limit 1
```

=== "PowerShell (Windows)"

```powershell
py -m cookbook --list
py -m cookbook optimization.cache_warming_and_ttl --limit 2 --ttl 3600
py -m cookbook production.resume_on_failure --limit 1
```

=== "CMD (Windows)"

```bat
py -m cookbook --list
py -m cookbook optimization\\cache-warming-and-ttl.py -- --limit 2 --ttl 3600
py -m cookbook production.resume_on_failure --limit 1
```

## Recipe Catalog

All recipes support `--mock / --no-mock`, `--provider`, `--model`, and `--api-key` flags. Start in `--mock` to validate flow, switch to `--no-mock` when prompts are stable.

| Recipe | Spec | Use it when you want to... | Learn the concept in docs |
|---|---|---|---|
| Analyze Single Paper | `getting-started/analyze-single-paper` | validate your install and inspect one result from one source | [Sending Content to Models](../sending-content.md) |
| Broadcast Process Files | `getting-started/broadcast-process-files` | process a directory with the same analysis prompts per file | [Analyzing Collections with Source Patterns](../source-patterns.md) |
| Structured Output Extraction | `getting-started/structured-output-extraction` | return typed objects instead of parsing JSON by hand | [Extracting Structured Data](../structured-data.md) |
| Extract Media Insights | `getting-started/extract-media-insights` | analyze one image, audio file, or video with the same entry point | [Sending Content to Models](../sending-content.md) |
| Paper-to-Workshop Kit | `projects/paper-to-workshop-kit` | turn one paper into a discussion-ready packet with slides, questions, objections, and actions | [Reducing Costs with Context Caching](../caching.md) |
| Run vs RunMany | `optimization/run-vs-run-many` | compare prompt loops against one `run_many()` call | [Analyzing Collections with Source Patterns](../source-patterns.md) |
| Cache Warming and TTL | `optimization/cache-warming-and-ttl` | measure cache reuse and choose a TTL for repeated prompts | [Reducing Costs with Context Caching](../caching.md) |
| Large-Scale Fan-Out | `optimization/large-scale-fan-out` | fan out per-file work with bounded client-side concurrency | [Analyzing Collections with Source Patterns](../source-patterns.md) |
| Comparative Analysis | `research-workflows/comparative-analysis` | compare two sources and emit structured JSON output | [Analyzing Collections with Source Patterns](../source-patterns.md) |
| Multi-Video Synthesis | `research-workflows/multi-video-synthesis` | synthesize themes across multiple video sources | [Analyzing Collections with Source Patterns](../source-patterns.md) |
| Rate Limits and Concurrency | `production/rate-limits-and-concurrency` | tune concurrency without overrunning provider limits | [Configuring Pollux](../configuration.md) |
| Resume on Failure | `production/resume-on-failure` | checkpoint long-running work and resume failed items | [Handling Errors and Recovery](../error-handling.md) |

### Learning Paths

**First successful runs:** `analyze-single-paper` → `broadcast-process-files` →
`structured-output-extraction` → `comparative-analysis`

**Efficiency and scale:** `run-vs-run-many` → `cache-warming-and-ttl` → `large-scale-fan-out`

**Build something useful:** `analyze-single-paper` → `projects/paper-to-workshop-kit`

**Production hardening:** `rate-limits-and-concurrency` → `resume-on-failure`

### Setup

```bash
uv sync --all-extras          # installs all dev/test/docs/lint deps
python -m cookbook --list      # verify install
just demo-data                # seed demo inputs
```

## Troubleshooting

- `could not import pollux`: run `uv sync --all-extras`.
- `Recipe not found`: verify the spec with `python -m cookbook --list`.
- Unexpected relative-path behavior: use `--no-cwd-repo-root` only when you need CWD-local paths.
- **No demo files:** run `just demo-data` or provide explicit `--input` paths.
- **API auth errors:** set `GEMINI_API_KEY`/`OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/`OPENROUTER_API_KEY`, then use `--no-mock`.
- **Rate limits:** lower concurrency and stage workload size with `--limit`.
