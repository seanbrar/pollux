# Contributing

Thanks for considering a contribution to Pollux. Whether it's a bug fix, a
new cookbook recipe, or a docs improvement — small, focused changes with clear
rationale are what move this project forward.

## Development Setup

We use `uv` for dependency management:

```bash
uv sync --all-extras          # or: pip install -e ".[dev]"
make check                    # lint + typecheck + tests
```

## Before Opening a PR

1. Run `make check` (lint + typecheck + tests).
2. If docs changed, preview locally: `make docs-serve`.
3. Write a test plan — describe how you verified the change and why.
4. Keep changes focused: one PR, one idea.

## Pull Requests

**Title:** Conventional Commits style — `type(scope): subject` (imperative).

Examples: `feat(api): add playlist support`, `fix(cache): handle expired tokens`,
`docs(cookbook): add source-pattern recipe`.

**Body** follows the [PR template](https://github.com/seanbrar/pollux/blob/main/.github/PULL_REQUEST_TEMPLATE.md):

1. **Summary** — what and why, one or two sentences
2. **Related issue** — `Closes #123`, or "None" for unprompted changes
3. **Test plan** — describe verification with evidence
4. **Notes** (optional) — context not obvious from the diff

**Checklist:**

- [ ] PR title follows conventional commits
- [ ] `make check` passes
- [ ] Tests cover meaningful cases, not just the happy path
- [ ] Docs updated if public API or user-facing behavior changed

## Issues

Issue templates exist for [bugs](https://github.com/seanbrar/pollux/issues/new?template=bug.md) and [feature requests](https://github.com/seanbrar/pollux/issues/new?template=feature.md). Keep issues small and concrete.

When a PR addresses an issue, link it in the **Related issue** section using
closing keywords (`Closes #123`, `Fixes #456`).

## Testing Philosophy

This project follows the [MTMT (Minimal Tests, Maximum Trust)](https://github.com/seanbrar/minimal-tests-maximum-trust) testing standard. See [TESTING.md](https://github.com/seanbrar/pollux/blob/main/TESTING.md) for guidance.

Every PR includes a test plan. The MTMT criteria — architectural guarantee,
boundary coverage, trivial delegation, non-behavioral change — are the
vocabulary for explaining why tests were or weren't added.

## Documentation Standards

Docs are user-facing first. Prioritize clarity, speed to success, and accurate
examples. When in doubt, cut.

- Clear purpose per page; one mode per page
- Runnable steps (snippets include imports)
- Accurate and single-sourced; cross-link where helpful
- Concise, active voice; safe by default (no secrets)

If you add or move pages, update `mkdocs.yml`.

## Cookbook Recipes

Recipes live in `cookbook/`, organized by scenario. Each recipe should:

- Start with a specific problem statement or scenario
- Provide runnable code with clear inputs and expected output
- Be self-contained (no ambient CWD assumptions)
- Support `--mock` and `--no-mock` modes

Structure flows from the scenario — there's no rigid section template. That
said, most good recipes cover: what you'll run, what you'll see, how to tune
it, and where to go next. Look at existing recipes for examples.

**Running recipes:**

```bash
python -m cookbook --list
python -m cookbook getting-started/analyze-single-paper --mock
```

**Adding a recipe:** create the Python script in `cookbook/<category>/`, add a
corresponding docs page in `docs/cookbook/<category>/`, and update `mkdocs.yml`.
Reuse shared runtime args from `cookbook.utils.runtime`.
