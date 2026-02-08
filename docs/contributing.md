# Contributing

This project values small, focused changes with clear rationale and easy verification.

## Development Setup

We use `uv` for dependency management:

```bash
# Install dependencies and setup virtualenv
uv sync --all-extras

# Or using the Makefile
make install-dev

# Verify setup
make test
```

## Before Opening a PR

1. Run `make check` (lint + typecheck + tests)
2. If docs changed, preview locally: `make docs-serve`
3. Write a test plan—describe how you verified the change and why (see [Testing Philosophy](#testing-philosophy))
4. Keep changes focused: one PR, one idea

## Pull Requests

**Title**: Conventional Commits style—`type(scope): subject` (imperative)

Examples:

- `feat(api): add playlist support`
- `fix(cache): handle expired tokens`
- `docs(cookbook): add batch processing recipe`

**Body** follows the [PR template](https://github.com/seanbrar/pollux/blob/main/.github/PULL_REQUEST_TEMPLATE.md) with four sections:

1. **Summary** — what and why, one or two sentences
2. **Related issue** — link with closing keywords (`Closes #123`), or "None" for unprompted changes
3. **Test plan** — describe verification with evidence; if no new tests, explain why (see [Testing Philosophy](#testing-philosophy))
4. **Notes** (optional) — context not obvious from the diff: rationale, trade-offs, deferred work, when to revisit

**Checklist** (mirrors the template checkboxes):

- [ ] PR title follows conventional commits
- [ ] `make check` passes
- [ ] Tests cover meaningful cases, not just the happy path
- [ ] Docs updated if public API or user-facing behavior changed

## Issues

Issue templates exist for [bugs](https://github.com/seanbrar/pollux/issues/new?template=bug.md) and [feature requests](https://github.com/seanbrar/pollux/issues/new?template=feature.md). Keep issues small and concrete. The templates carry most of the detail; at a glance:

- **Bug reports**: what happened, expected behavior, reproduction steps, error output, environment (Pollux/Python/OS, provider + model if applicable)
- **Feature requests**: problem or use case, optional proposed change, optional acceptance criteria / out of scope

When a PR addresses an issue, link it in the **Related issue** section using closing keywords (`Closes #123`, `Fixes #456`).

Issues may also be filed during development when bugs or deferred work items are discovered out of scope of the current task. These follow the same templates and quality bar as any other issue.

## Testing Philosophy

This project follows the [MTMT (Minimal Tests, Maximum Trust)](https://github.com/seanbrar/minimal-tests-maximum-trust) testing standard. See [TESTING.md](https://github.com/seanbrar/pollux/blob/main/TESTING.md) for guidance on what merits a test.

Every PR includes a test plan. The MTMT criteria—architectural guarantee, boundary coverage, trivial delegation, non-behavioral change—are the vocabulary for explaining why tests were or weren't added.

## Documentation Standards

Docs are user-facing first. Prioritize clarity, speed to success, and accurate examples. When in doubt, cut.

**Quality checklist:**

- Clear purpose and audience; one mode per page
- Runnable steps (snippets include imports), explicit success checks
- Accurate and single-sourced; cross-link where helpful
- Concise, active voice; safe by default (no secrets)
- Call out real API usage and costs when relevant

If you add or move pages, update `mkdocs.yml`.

## Cookbook Recipes

Recipes require a dev install (`uv sync --all-extras` or `pip install -e ".[dev]"`) so that `import pollux` resolves through the package manager.

Recipes live in `cookbook/`, organized by scenario. Each recipe should:

- Start with a specific problem statement
- Provide runnable code with clear inputs/outputs
- Include expected success checks
- Be self-contained (no ambient CWD assumptions)

**Running recipes:**

```bash
python -m cookbook --list
python -m cookbook getting-started/analyze-single-paper -- --limit 1
```

**Recipe template:**

```python
"""Recipe: [Descriptive Problem Statement]

When you need to: [One sentence describing the scenario]

Ingredients:
- [Prereqs: API key, data, deps]

What you'll learn:
- [Key concept 1]
- [Key concept 2]
"""

import asyncio
from pollux import run_simple, types

async def main():
    # Implementation
    ...

if __name__ == "__main__":
    asyncio.run(main())
```
