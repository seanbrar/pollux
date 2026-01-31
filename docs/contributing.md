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

1. Run checks: `make check`
2. If docs changed, preview locally: `make docs-serve`
3. Keep changes focused: one PR, one idea

## Pull Requests

**Title**: Conventional Commits style—`type(scope): subject` (imperative)

Examples:
- `feat(api): add playlist support`
- `fix(cache): handle expired tokens`
- `docs(cookbook): add batch processing recipe`

**Body**:
1. Summary—what does this PR do? One or two sentences.
2. Notes (optional)—anything reviewers should know.

## Testing Philosophy

This project follows the [MTMT (Minimal Tests, Maximum Trust)](https://github.com/seanbrar/minimal-tests-maximum-trust) testing standard. See [TESTING.md](https://github.com/seanbrar/pollux/blob/main/TESTING.md) for guidance on what merits a test.

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
