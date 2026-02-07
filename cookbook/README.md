# Pollux Cookbook

Practical, problem-first recipes for multimodal analysis with Pollux.

This folder contains the runnable recipe code. The canonical cookbook
documentation (learning paths, recipe pages, and authoring guidance) lives under
`docs/cookbook/` and is published on the documentation site.

- Start here: `docs/cookbook/index.md`
- Recipe templates: `docs/cookbook/templates.md`

## Setup

Recipes require a dev install so that `import pollux` resolves through the package manager:

```bash
uv sync --all-extras          # or: pip install -e ".[dev]"
```

Then seed demo inputs:

```bash
make demo-data
```

## Quick start

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
