# Agent Guidelines (Pollux)

This is the operating guide for AI coding agents working in this repository.
It should help an agent make good first moves, preserve project boundaries, and
verify work without duplicating facts that are easy to read from the code.

Use these files as the source of truth when they are relevant:

- `src/pollux/__init__.py` - public API exports and entry-point behavior
- `src/pollux/config.py` - providers, credentials, and config validation
- `src/pollux/providers/` - provider adapters and capability boundaries
- `TESTING.md` - testing philosophy and boundary-first structure
- `ROADMAP.md` - scope boundaries and post-1.0 candidates
- `docs/contributing.md` - human contributor and PR guidance
- `.github/PULL_REQUEST_TEMPLATE.md` - required PR body format

## Project Context

Pollux is a Python library for multimodal orchestration on LLM APIs. Users
describe what to analyze; Pollux handles source patterns, context caching, rate
limits, retries, provider differences, and result normalization.

The main execution model is:

```text
Request -> Plan -> Execute -> Extract
```

The implementation follows that shape across `request.py`, `plan.py`,
`execute.py`, and `result.py`. Keep provider-specific SDK calls inside
`src/pollux/providers/`; code above that boundary should work through Pollux's
provider abstractions.

## Vocabulary

Use project terms precisely:

| Term | Meaning |
| ---- | ------- |
| Context caching | Uploading content once and reusing it across prompts |
| Fan-out | One source -> many prompts |
| Fan-in | Many sources -> one prompt |
| Broadcast | Many sources x many prompts |
| Source patterns | Fan-out, fan-in, and broadcast collectively |
| Deferred mode | Provider-side asynchronous job APIs exposed through Pollux deferred entry points |

When writing docs or comments, prefer "source patterns" for Pollux's
multi-source/multi-prompt behavior and use "deferred" for provider-side async
jobs.

## Repo Map

- `src/pollux/` - library code
- `tests/` - flat, boundary-first test suite
- `docs/` - MkDocs site; navigation lives in `mkdocs.yml`
- `cookbook/` - runnable, user-facing recipes
- `scripts/` - helper scripts

## Agent Workflow

Start by turning the request into an executable spec: expected inputs, outputs,
edge cases, and what counts as done. Identify the boundary being changed, such
as public API, provider adapter, execution planning, result extraction, docs, or
cookbook.

For non-trivial work, search related open issues before editing:

```bash
gh issue list --state open --search "<keywords>"
```

Search the codebase before adding modules, abstractions, or public API. Let the
existing tests and nearby code determine the shape of the change.

Make the smallest coherent change that satisfies the spec. Keep public APIs
stable unless the task explicitly asks for a breaking change. Remove dead code
introduced by the change instead of parking unused paths in `src/pollux/`.

Ask questions only when the answer changes the correct design and cannot be
discovered from the repository. Otherwise, make a reasonable assumption, state
it, and keep moving.

If a local CLI behaves differently because of the execution environment, capture
the failure, try a reasonable fallback, and report any remaining blocker in the
final response.

## Verification

Add or adjust tests when behavior changes. Prefer narrow verification first,
then broader checks when the risk justifies it.

Common commands:

```bash
just install-dev
just format
just lint
just typecheck
just test
just check
uv run pytest tests/test_config.py -v
uv run pytest tests/test_pipeline.py::test_name -v
uv run pytest -m "unit" -v
```

Use `just check` before a PR or after non-trivial changes when feasible. If you
do not add tests, explain why with MTMT vocabulary:

- Architectural guarantee - the design makes the bug class impossible
- Boundary coverage - existing tests already cover the affected boundary
- Trivial delegation - the change delegates to already-tested code
- Non-behavioral change - docs, comments, formatting, or config-only changes

API tests are opt-in. They must be marked `api`, skip cleanly without
credentials, and are gated by `ENABLE_API_TESTS=1`. Run them only when asked or
when real provider verification is necessary.

Tests intentionally isolate environment and dotenv behavior by default. Check
`tests/conftest.py` before changing credential, dotenv, or provider-env tests.

## Code Style

- Format with Ruff: 88 columns, double quotes.
- Library code is strictly typed with mypy; tests allow untyped defs.
- Use `snake_case` for functions/modules and `PascalCase` for classes.
- Use Google-style docstrings where docstrings are needed.
- Keep supported Python versions and tool settings aligned with `pyproject.toml`.

## Docs And Cookbook

Docs and cookbook recipes are user-facing. Keep them runnable, explicit, and
safe by default: no secrets, no ambient CWD assumptions, and no provider calls
hidden behind surprising defaults.

Update docs in the same PR when public API or user-facing behavior changes. If
you add or move docs pages, update `mkdocs.yml`.

The cookbook is a clone-and-run teaching artifact, not part of the wheel and not
a console entry point. Recipes should run on a fresh clone with the tiny seed
data under `cookbook/data/seed/`; heavier assets belong in the optional
`pollux-cookbook-data` path loaded by `just demo-data`.

## Security

Keep provider calls explicit and testable. Default to mock or non-networked
verification unless the task requires real provider access.

Never commit real keys. `.env` is local-only; `.env.example` is the template.
Credential and local-provider behavior should follow `src/pollux/config.py`.

## Issues And PRs

Use GitHub issues when they help future work:

- Search for related issues before creating one.
- File issues for concrete bugs, doc drift, or out-of-scope follow-ups a human
  maintainer would reasonably act on.
- Add comments only when you have useful technical context: reproduction,
  root cause, scope clarification, or implementation notes.

Commit and PR titles use conventional commits: `type(scope): subject`.
Common scopes include `api`, `core`, `cookbook`, `tests`, `ci`, `deps`, `docs`,
and `config`; use a bare type for cross-cutting changes.

Before opening a PR, make sure:

- The PR body follows `.github/PULL_REQUEST_TEMPLATE.md`
- The related issue section says `Closes #...`, `Relates to #...`, or `None`
- The test plan names exact commands and evidence
- User-facing behavior changes include docs or cookbook updates

For separable follow-up work, prefer a second branch or worktree so the current
change stays reviewable:

```bash
git fetch origin
git worktree add -b <branch> .worktrees/<topic> origin/main
cd .worktrees/<topic>
just check
git add -A
git commit -m "fix(scope): <subject>"
git push -u origin <branch>
gh pr create
```

## Final Response

Summarize what changed, why it changed, risks or non-goals, and the exact
commands run. If verification was skipped or incomplete, say so directly.
