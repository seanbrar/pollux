# Pollux Cookbook

Practical, problem-first recipes for multimodal analysis with Pollux.

This folder contains runnable recipe code. The teaching layer lives in the
published docs under `docs/`, where each concept has one authoritative page.
Use the cookbook when you want a complete script you can run and modify after
you understand the concept. Some recipes are compact on-ramps; others are small
forkable applications under `cookbook/projects/`.

- Learn the API and boundaries in `docs/getting-started.md`,
  `docs/sending-content.md`, `docs/source-patterns.md`, and related topical pages
- Find recipe specs and descriptions in `docs/reference/cli.md`
- Start from a template in `cookbook/templates/`

## Setup

Recipes require a dev install so that `import pollux` resolves through the package manager:

```bash
uv sync --all-extras          # or: pip install -e ".[dev]"
```

Then seed demo inputs:

```bash
just demo-data
```

## Quick start

```bash
# 1) List recipes
python -m cookbook --list

# 2) Run a baseline recipe in mock mode (default)
python -m cookbook getting-started/analyze-single-paper \
  --input cookbook/data/demo/text-medium/input.txt

# 3) Run a project recipe
python -m cookbook projects/paper-to-workshop-kit \
  --input cookbook/data/demo/multimodal-basic/sample.pdf

# 4) Run against a real provider
python -m cookbook getting-started/analyze-single-paper \
  --input path/to/file.pdf --no-mock --provider gemini --model gemini-2.5-flash-lite
```

Notes:

- Use `just demo-data` for local sample inputs.
- Most recipes support `--mock/--no-mock`, `--provider`, and `--model`.
