# Agent Guidelines (Pollux)

This file is the authoritative operating manual for AI coding agents working in
this repo. It covers project context, architecture, workflows, and guardrails.

Supplementary references:
- `TESTING.md` — Testing philosophy and boundary-first structure
- `ROADMAP.md` — Scope boundaries, post-1.0 candidates
- `docs/contributing.md` — Human contributor guide (PR/docs/cookbook standards)
- `.github/PULL_REQUEST_TEMPLATE.md` — PR body template

## Project Overview

Pollux is a Python library for multimodal orchestration on LLM APIs. It
provides source patterns (fan-out, fan-in, broadcast), context caching, and a
modern async pipeline for analyzing text, PDFs, images, videos, and YouTube
URLs.

**Core value:** You describe what to analyze. Pollux handles source patterns,
context caching, rate limits, and retries—so you don't.

## Vocabulary

Use precise terms to avoid confusion with provider-specific features:

| Term | Definition |
|------|------------|
| **Context caching** | Uploading content once, reusing across prompts |
| **Fan-out** | One source → many prompts |
| **Fan-in** | Many sources → one prompt |
| **Broadcast** | Many sources × many prompts |
| **Source patterns** | Fan-out, fan-in, broadcast collectively |
| **Deferred mode** | (Future) Provider's async batch API (e.g., Google's Batch Prediction) |

**Avoid:** "batch processing" alone—it's ambiguous with provider batch APIs.

## Project Map

| Path | Contents |
|------|----------|
| `src/pollux/` | Library code |
| `tests/` | Tests (flat, boundary-first) |
| `docs/` | MkDocs site; navigation in `mkdocs.yml` |
| `cookbook/` | Runnable recipes (user-facing) |
| `scripts/` | Helper scripts |

## Architecture

### Four-Phase Pipeline

```
Request → Plan → Execute → Extract
```

1. **Request Normalization** (`src/pollux/request.py`): Validates and normalizes prompts, sources, and config into a canonical `Request` dataclass
2. **Execution Planning** (`src/pollux/plan.py`): Converts request into an execution plan with API calls; computes deterministic cache keys from content hashes
3. **Plan Execution** (`src/pollux/execute.py`): Executes the plan asynchronously with file uploads, context caching, and concurrent API calls
4. **Result Extraction** (`src/pollux/result.py`): Transforms API responses into standardized `ResultEnvelope` with `answers`, optional `structured`, and `usage` metadata

### Entry Points

The public API is exposed through `src/pollux/__init__.py`:

- **`run(prompt, *, source=None, config, options=None)`** — Single prompt execution
- **`run_many(prompts, *, sources=(), config, options=None)`** — Multi-prompt execution with shared sources (source patterns)

### Key Modules

| Module | Purpose |
|--------|---------|
| `config.py` | Immutable `Config` dataclass with API key resolution |
| `source.py` | `Source` factory with `from_text()`, `from_file()`, `from_youtube()`, `from_arxiv()` |
| `options.py` | Execution options: `response_schema`, `reasoning_effort`, `delivery_mode` (and reserved conversation inputs) |
| `cache.py` | `CacheRegistry` for TTL-based context cache management |
| `errors.py` | Exception hierarchy with `.hint` attribute for actionable messages |
| `retry.py` | `RetryPolicy` + bounded async retry used by execution and providers |
| `providers/` | Provider implementations: `gemini.py`, `openai.py`, `mock.py` |

### Provider Abstraction

Providers live behind a common interface in `src/pollux/providers/`. Each
provider module translates Pollux's internal plan into provider-specific API
calls. The boundary is strict: library code above `providers/` never imports
provider SDKs directly.

### Environment Variables

- `GEMINI_API_KEY` — Gemini API key (auto-loaded from `.env`)
- `OPENAI_API_KEY` — OpenAI API key (auto-loaded from `.env`)

### Async Model

The pipeline is async end-to-end. `run()` and `run_many()` are coroutines.
Synchronous callers use `asyncio.run()`.

## Agent Operating Procedure

### 1. Orient

- Restate the goal as an executable spec: inputs, outputs, edge cases, and
  what counts as done.
- Find the boundary you're changing (public API, provider adapter, CLI, etc.).
- Search for related open issues before starting work:
  `gh issue list --state open --search "<keywords>"`
- Search the codebase before inventing new modules or abstractions.
- Be action-forward: gather context with safe, read-only operations and only
  stop to ask questions when ambiguity would change the correct design.

### 2. Change Minimally

- Prefer the smallest diff that satisfies the spec.
- Keep public APIs stable unless the task explicitly calls for breaking change.
- Avoid dead code in `src/pollux/`; delete unused paths rather than parking
  them.

### 3. Verify

- Add or adjust tests when behavior changes.
- Use MTMT vocabulary when you intentionally do not add tests:
  architectural guarantee, boundary coverage, trivial delegation,
  non-behavioral change.
- Verify incrementally: run the narrowest check that builds confidence first
  (a single test file or marker), then finish with `just check` for
  non-trivial changes.

### 4. Communicate

- In your final response: what changed, why, risks, and exact commands run.
- Call out deliberate non-goals or follow-ups (but do not expand scope).

## Build & Development Commands

### Install

```bash
just install-dev          # Install all dev/test/docs/lint deps via uv
```

### Verify (full suite)

```bash
just check                # lint + typecheck + tests
just test                 # All tests (except API tests)
just test-api             # API tests (requires ENABLE_API_TESTS=1 + at least one provider API key)
just lint                 # Ruff format check + lint
just typecheck            # Mypy strict checks
```

### Fix

```bash
just format               # Auto-format and apply safe Ruff fixes
```

### Narrow (single target)

```bash
uv run pytest tests/test_config.py -v             # Single test file
uv run pytest tests/test_pipeline.py::test_name -v # Single test
uv run pytest -m "unit" -v                         # By marker
```

### Docs & Demo Data

```bash
just docs-serve           # Serve docs locally at http://127.0.0.1:8000
just docs-build           # Build the documentation site
just demo-data            # Fetch demo data into cookbook/data/demo/
```

## Testing

Tests follow a **boundary-first flat structure**. See [TESTING.md](TESTING.md)
for the full testing philosophy.

### Test Files

| File | Purpose |
|------|---------|
| `test_source.py` | Source boundary: factory methods, validation, normalization |
| `test_pipeline.py` | Pipeline boundary: public API, request normalization, caching, options forwarding |
| `test_config.py` | Config boundary: resolution, validation, redaction |
| `test_providers.py` | Provider characterization: request/response shapes |
| `test_api.py` | Real API integration (Gemini + OpenAI, requires `ENABLE_API_TESTS=1`) |
| `test_cookbook.py` | Cookbook CLI runner boundary |

### Markers

Tests use pytest markers for selection: `unit`, `integration`, `api`, `slow`.

### Test Isolation

Autouse fixtures in `tests/conftest.py` provide environment isolation:

| Fixture | Default behavior | Opt-out marker |
|---------|-----------------|----------------|
| `block_dotenv()` | Prevents `.env` loading | `@pytest.mark.allow_dotenv` |
| `isolate_provider_env()` | Cleans `GEMINI_*` and `OPENAI_*` env vars | `@pytest.mark.allow_env_pollution` |

API test fixtures (not autouse):

- `gemini_api_key` — Returns `GEMINI_API_KEY` or skips test
- `openai_api_key` — Returns `OPENAI_API_KEY` or skips test

### API Test Rules

- Must be explicitly marked `api`.
- Must skip cleanly without credentials.
- Gated by `ENABLE_API_TESTS=1` (otherwise skipped).
- Do not run them unless asked or the change genuinely requires provider
  verification.

### Coverage

Coverage is tracked in CI via Codecov (diagnostic only, no enforced targets).

## Code Style

- **Formatting:** Ruff (88 cols, double quotes). Use `just format` after edits.
- **Types:** Library code uses strict mypy (`disallow_untyped_defs = true`).
  Tests are exempt from `disallow_untyped_defs`.
- **Naming:** `snake_case` for functions/modules, `PascalCase` for classes.
- **Docstrings:** Google style.
- **Compatibility:** Packaging supports Python `>=3.10,<3.15`; dev commonly
  uses 3.13 (see `.python-version`).

## Contributing Workflow

See `docs/contributing.md` for the full human contributor guide. The guidance
below focuses on judgment calls agents face regularly.

### Conventional Commits

Commit and PR titles use `type(scope): subject` (imperative mood). Common
scopes: `api`, `core`, `cookbook`, `tests`, `ci`, `deps`, `docs`, `config`.
Use bare types (`feat:`, `fix:`, `docs:`, `chore:`) for cross-cutting changes.
These are examples, not a fixed allowlist.

### Pull Requests

The repo has a [PR template](.github/PULL_REQUEST_TEMPLATE.md) with four
sections:

1. **Summary** — what and why, one or two sentences
2. **Related issue** — link with closing keywords (`Closes #123`), or "None"
   for unprompted changes
3. **Test plan** — describe verification with evidence (see test plan guidance)
4. **Notes** (optional) — context not obvious from the diff

Before opening, ensure:

- PR title follows conventional commits
- `just check` passes (lint + typecheck + tests)
- Tests cover meaningful cases, not just the happy path
- Docs updated if public API or user-facing behavior changed

### GitHub Issues Workflow

Use `gh` (GitHub CLI) to work with issues as a natural part of development.

**Reading issues (proactive, every task):**

At the start of any non-trivial task, check for related open issues:

```bash
gh issue list --state open --search "<keywords relevant to the task>"
```

Also check issues before creating a PR — the work may fully or partially
resolve an existing issue.

**Creating issues:**

File issues for genuine findings discovered during development:

- Real bugs encountered that are out of scope for the current task
- Deferred work explicitly called out in the current PR
- Missing functionality that blocks or complicates the current task

Before creating, search for duplicates: `gh issue list --search "<summary>"`.
Use the repo's issue templates:

```bash
# Non-interactive (recommended): start from the template content in
# .github/ISSUE_TEMPLATE/{bug,feature}.md, then file via --body-file.
gh issue create --title "fix(scope): summary" --body-file /tmp/issue.md
```

Issue titles follow the same conventional commits format as PR titles.

**Do not create issues for**: speculative improvements, style preferences,
vague TODOs, or anything the current PR already addresses. The bar: *would a
human contributor file this?*

**Commenting on issues:**

Add a comment when you have **substantive information** to contribute: root
cause analysis, reproduction details, scope clarification, or technical context
that would help whoever picks up the issue next.

Do not comment just to signal activity — the linked PR sidebar already shows
that.

```bash
gh issue comment <number> --body "<substantive context>"
```

**Linking issues in PRs:**

Always populate the **Related issue** section of the PR template:

- `Closes #123` / `Fixes #123` — when the PR fully resolves the issue
- `Relates to #123` — when partial or tangential
- `None` — for unprompted changes with no related issue

### Test Plan Guidance

Every PR includes a test plan. When no new tests are added, explain why using
[MTMT](https://github.com/seanbrar/minimal-tests-maximum-trust) vocabulary:

- **Architectural guarantee** — the design makes the bug class impossible
- **Boundary coverage** — existing tests already cover the affected boundary
- **Trivial delegation** — the change delegates to already-tested code with no
  new logic
- **Non-behavioral change** — docs, comments, formatting, or config-only
  changes

## Documentation & Cookbook

- Docs and cookbook recipes are user-facing. Keep them runnable, explicit, and
  safe-by-default (no secrets, no ambient CWD assumptions).
- If you add or move docs pages, update `mkdocs.yml`.
- If you change user-facing behavior or public API, update docs in the same PR.

## Security & Safety

- Never commit real keys. `.env` is local-only; `.env.example` is the template.
- Default to mock or non-networked verification unless the task requires real
  provider calls.
- Avoid introducing "quiet" network behavior in library code: make provider
  calls explicit and testable.

## Codex Sandbox

In Codex, repo-facing CLIs like `git` and `gh` may need to run **outside the
sandbox**. If they are blocked or behave oddly, rerun via `functions.exec_command`
with `sandbox_permissions="require_escalated"`. For `gh`, saved command prefixes
only auto-approve on the user side; live GitHub API calls (issues search/list/view,
`gh api`, etc.) still require an out-of-sandbox execution.

## Initiative (Judgment Calls)

Agents should make judgment calls, but keep scopes clean.

- If you discover a **real bug**, **doc drift**, or **out-of-scope follow-up**
  that would help even a solo maintainer: file an issue. Use the same bar as a
  human contributor: *would this be worth documenting for later?*
- If a follow-up is small and clearly separable: prefer a **second PR** rather
  than expanding the current one. A separate branch/worktree is encouraged when
  available.
- Avoid noise: do not open issues for speculative refactors, style preferences,
  or “maybe someday” ideas.

### Follow-up PR via worktree (recommended)

Keep the current PR clean by doing follow-up work on a new branch in a new
worktree:

```bash
git fetch origin
git worktree add -b <branch> .worktrees/<topic> origin/main
cd .worktrees/<topic>
just check
git add -A && git commit -m "fix(scope): <subject>" && git push -u origin <branch>
gh pr create
```

Notes:
- New worktrees do not include untracked local files (example: `.env`); prefer
  explicit environment variables when running API tests.
- Run commands from inside the worktree to avoid testing/committing from the
  wrong directory.

## Known Footguns

- **API tests are double-gated.** `tests/` skip `@pytest.mark.api` unless
  `ENABLE_API_TESTS=1` is set (even if keys are present). `just test-api`
  selects `-m api`, but you still need `ENABLE_API_TESTS=1`.
- **`.env` is loaded lazily during `Config` initialization.** `src/pollux/config.py`
  calls `load_dotenv()` only when `api_key` is omitted and the provider key is
  not already exported. Tests intentionally block dotenv loading unless
  explicitly opted out.
- **Test isolation is intentional.** Autouse fixtures clear provider env vars
  and redirect home config by default; opt out only when the test requires it.
- **Prefer the code as source of truth for API names.** The public API is
  exported from `src/pollux/__init__.py` (`run`, `run_many`). If docs/cookbook
  mention stale names (example: `batch`), treat it as doc drift and consider
  fixing in a follow-up.
