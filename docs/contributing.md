# Contributing

Bug fixes, focused features, and documentation improvements are welcome.

## Development Setup

We use `uv` for dependency management:

```bash
uv sync                       # installs the project + dev/test/docs/lint deps
just check                    # lint + typecheck + tests
```

Requires Python `>=3.10,<3.15` (3.13 recommended).

## Making a Change

Keep changes focused and run `just check` before submitting them. If the docs
change, also run `just docs-build` or preview them with `just docs-serve`.

Maintainers normally commit directly to `main`. Larger changes may use a branch
and reach `main` by fast-forward or squash merge. Pull requests are for external
contributions and occasions when independent review is useful; there is no
required body template.

Commit subjects use `<area>: <imperative summary>`, for example
`cache: reuse uploads across fan-out`. Use a body only for motivation or a
trade-off that is not apparent from the diff.

## Issues

Issue templates exist for [bugs](https://github.com/seanbrar/pollux/issues/new?template=bug.md) and [feature requests](https://github.com/seanbrar/pollux/issues/new?template=feature.md). Keep issues small and concrete.

Link an issue when the change actually resolves one; an issue is not required
before making a change.

## Testing Philosophy

Tests should protect the boundary affected by the change. See
[TESTING.md](https://github.com/seanbrar/pollux/blob/main/TESTING.md) for the
suite layout and commands.

## Documentation Standards

Docs are user-facing first. Prioritize clarity, speed to success, and accurate
examples. When in doubt, cut.

- Defined purpose per page; one mode per page
- Runnable steps (snippets include imports)
- Accurate and single-sourced; cross-link where helpful
- Concise, active voice; safe by default (no secrets)

If you add or move pages, update `mkdocs.yml`.

## Cookbook Recipes

Recipes live in `cookbook/`, organized by scenario. Each recipe should:

- Start with a specific problem statement or scenario
- Provide runnable code with explicit inputs and expected output
- Be self-contained (no ambient CWD assumptions)
- Support `--mock` and `--no-mock` modes

Recipes complement the docs. They are runnable starting points, not a second
teaching layer. If a recipe introduces or depends on a user-facing concept,
the authoritative explanation belongs on the matching page under `docs/`.

Structure flows from the scenario — there's no rigid section template. Most
good recipes cover: what you'll run, what you'll see, how to tune it, and
where to go next. Look at existing recipes for examples.

**Running recipes:**

```bash
python -m cookbook --list
python -m cookbook getting-started/analyze-single-paper --mock
```

**Adding a recipe:** create the Python script in `cookbook/<category>/` and
reuse shared runtime args from `cookbook.utils.runtime`. The recipe catalog
in [CLI](reference/cli.md#recipe-catalog) lists all available recipes. Update
the authoritative topical docs in the same change when the recipe adds a new
concept or changes user-facing behavior.
