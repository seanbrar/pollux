# Contributing Guide

This project values small, focused changes with clear rationale and easy verification. Follow these conventions to keep momentum and clarity high.

## Pull requests

- Title: Conventional Commits style `type(scope): subject` (imperative). Example: `feat(api): add playlist support`.
- Body:
  1. Summary – what does this PR do? One or two sentences.
  2. Notes (optional) – anything reviewers should know, or context for your future self.
- Tests: If your PR includes tests, ensure they provide meaningful signal. See the [Testing Guide](../testing.md) for guidance on what merits a test.

## Documentation

We follow Diátaxis:

- Tutorials – first success walkthroughs.
- How‑to – task recipes with minimal theory.
- Reference – factual API and CLI details (generated where possible).
- Explanation – concepts, deep dives, and decisions (ADRs).

Quality checklist (abbrev.):

- Clear purpose and audience; one mode per page.
- Runnable steps (snippets include imports/env), explicit success checks.
- Accurate and single‑sourced; cross‑link tasks ↔ reference ↔ explanations.
- Concise, active voice; safe by default (no secrets, cost notes where relevant).
- Use Material features intentionally (admonitions, code copy, tabs when helpful).

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

## ADRs and deep dives

- Significant architectural decisions should be recorded as an ADR in Explanation → Decisions, and referenced from related deep dives.
- Superseded proposals remain internal; public docs reflect the current or target architecture as marked.

