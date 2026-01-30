# Contributing Guide

This project values small, focused changes with clear rationale and easy verification. Follow these conventions to keep momentum and clarity high.

## Pull requests

- Title: Conventional Commits style `type(scope): subject` (imperative). Example: `feat(api): add playlist support`.
- Body:
  1. Summary - what does this PR do? One or two sentences.
  2. Notes (optional) - anything reviewers should know, or context for your future self.
- Tests: If your PR includes tests, ensure they provide meaningful signal. See
  [TESTING.md](https://github.com/seanbrar/gemini-batch-prediction/blob/main/TESTING.md)
  for guidance on what merits a test.

## Documentation

Docs are user-facing first. Prioritize clarity, speed to success, and accurate examples.
When in doubt, cut.

We follow Diataxis:

- Tutorials - first success walkthroughs.
- How-to - task recipes with minimal theory.
- Reference - factual API and CLI details (generated where possible).
- Explanation - concepts and deep dives (keep these rare and focused).

Quality checklist (abbrev.):

- Clear purpose and audience; one mode per page.
- Runnable steps (snippets include imports/env), explicit success checks.
- Accurate and single-sourced; cross-link tasks <-> reference <-> explanations.
- Concise, active voice; safe by default (no secrets, cost notes where relevant).
- Use Material features intentionally (admonitions, code copy, tabs when helpful).

Practical guidance:

- Map intent to location: `docs/quickstart.md` (tutorial), `docs/guides/*` (how-to),
  `docs/reference/*` (reference). Keep one mode per page.
- Prefer public APIs in examples; avoid internal attributes and implementation details.
- Keep examples copy-pasteable: include imports, minimal setup, and expected output.
- Call out real API usage and costs when relevant; default to mock mode.
- Keep pages tight: remove tangents, move deep details to reference.

If you add or move pages, update `mkdocs.yml`. Preview with `make docs-serve`.
Cookbook recipes follow their own guide in `docs/contributing/cookbook_authoring.md`.

## Development Setup

We use `uv` for dependency management and development tasks.

```bash
# Install dependencies and setup virtualenv
uv sync --all-extras
```

## Before opening a PR

- Run: `make lint-all` and `make test-fast`. For broader checks: `make test-coverage`.
- If docs changed, build locally: `make docs-serve`.
- Keep changes focused: one PR, one idea.
