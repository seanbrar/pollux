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

Then install the shared starter data pack:

```bash
just demo-data
```

## Quick start

```bash
# 1) List recipes
python -m cookbook --list

# 2) Install starter inputs once, then let recipes fall back to them
just demo-data

# 3) Run a baseline recipe in mock mode (default)
python -m cookbook getting-started/analyze-single-paper

# 4) Run a project recipe
python -m cookbook projects/paper-to-workshop-kit

# 5) Run a multimodal project recipe
python -m cookbook projects/fridge-raid \
  --note "eggs, rice, scallions"

# 6) Run a DnD project recipe
python -m cookbook projects/treasure-tailor \
  --party-member "Nyx:rogue:5" \
  --party-member "Brakka:fighter:5" \
  --party-member "Iri:wizard:5" \
  --summary "The party cleared a flooded observatory."

# 7) Run a DnD spell packet recipe
python -m cookbook projects/spellbook-sidekick \
  --spell Shield \
  --spell Web \
  --spell Counterspell \
  --class wizard \
  --level 5

# 8) Run against a real provider
python -m cookbook getting-started/analyze-single-paper \
  --input path/to/file.pdf --no-mock --provider gemini --model gemini-2.5-flash-lite
```

Notes:

- `just demo-data` installs the shared starter data pack used by shared cookbook fallbacks.
- `just demo-data project=spellbook-sidekick` installs the authored spellbook starter pack.
- Most recipes support `--mock/--no-mock`, `--provider`, and `--model`.
