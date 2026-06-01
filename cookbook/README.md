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

Recipes need Pollux importable from a checkout. Install the project (this is all
you need to run recipes):

```bash
uv sync                       # or: pip install -e .
```

`uv sync` also installs the dev tooling used by `just check`; `pip install -e .`
installs just the library, which is enough to run recipes. Recipes run with no
extra setup — the repo ships a tiny seed of demo inputs, so the default path
works on a fresh clone. To add richer/heavier samples (audio, video, authored
project packs), install the optional data packs:

```bash
just demo-data                # optional: heavier shared media + a network fetch
```

## Quick start

```bash
# 1) List recipes
python -m cookbook --list

# 2) Run a baseline recipe in mock mode (default) — works on the in-repo seed
python -m cookbook getting-started/analyze-single-paper

# 3) Run a project recipe
python -m cookbook projects/paper-to-workshop-kit

# 4) Run a multimodal project recipe
python -m cookbook projects/fridge-raid \
  --note "eggs, rice, scallions"

# 5) Run a DnD project recipe
python -m cookbook projects/treasure-tailor \
  --party-member "Nyx:rogue:5" \
  --party-member "Brakka:fighter:5" \
  --party-member "Iri:wizard:5" \
  --summary "The party cleared a flooded observatory."

# 6) Run a DnD spell packet recipe (uses an authored pack: `just demo-data spellbook-sidekick`)
python -m cookbook projects/spellbook-sidekick \
  --spell Shield \
  --spell Web \
  --spell Counterspell \
  --class wizard \
  --level 5

# 7) Run against a real provider
python -m cookbook getting-started/analyze-single-paper \
  --input path/to/file.pdf --no-mock --provider gemini --model gemini-2.5-flash-lite
```

Notes:

- Recipes run on a tiny in-repo seed by default; `just demo-data` is optional and
  adds heavier shared media (audio, video) via a network fetch.
- `just demo-data spellbook-sidekick` installs the authored spellbook starter pack.
- Most recipes support `--mock/--no-mock`, `--provider`, and `--model`.
  If you omit `--model`, the cookbook picks a starter model for the selected
  provider.
