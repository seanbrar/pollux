# Working on Pollux

Pollux is a Python library for multimodal orchestration across LLM APIs. Users
describe what to analyze; Pollux handles sources, reusable context, retries,
provider differences, and normalized results.

## Find the boundary

Read the code closest to the change before inventing a new abstraction:

- `src/pollux/__init__.py` — public entry points and exports
- `src/pollux/config.py` — providers, credentials, and configuration
- `src/pollux/interaction/` — environment, input, execution, and output types
- `src/pollux/providers/` — provider SDK calls and capability differences
- `tests/` — expected behavior at each boundary

Provider-specific calls stay in `src/pollux/providers/`. Code above that
boundary works through Pollux's provider abstractions.

Use the project terms precisely when they help:

- **Context caching:** upload content once and reuse it across prompts.
- **Fan-out:** one source context, many prompts.
- **Fan-in:** many sources in one shared context, one prompt.
- **Broadcast:** application code repeats a prompt set across separate sources.
- **Deferred:** provider-side asynchronous jobs.

Do not add terminology merely to make a small operation sound architectural.

## Make the change

Search the repository and related open issues first. Preserve public behavior
unless the task explicitly permits a breaking change. Prefer the smallest
coherent implementation and remove obsolete paths instead of reserving them for
hypothetical future use.

For user-facing behavior, update the relevant documentation or cookbook example
in the same change. Examples must be runnable without ambient working-directory
assumptions or hidden provider calls.

## Verify it

Start narrow, then run the repository check before committing non-trivial work:

```bash
uv run pytest tests/path/to/test.py -v
just check
```

Run `just docs-build` when documentation or public API reference material
changes. Real provider tests are opt-in through `ENABLE_API_TESTS=1`; they must
skip cleanly without credentials.

When behavior changes, add a test at the affected boundary. When no test is
useful, explain the concrete reason in the commit body or final report rather
than selecting a phrase from a checklist.

## Git workflow

Maintainer changes do not use pull requests.

- A change that forms one coherent commit goes directly to `main`.
- Larger work uses a branch and several coherent commits, then reaches `main`
  by fast-forward or squash merge.
- Pull requests remain available for contributions from people who cannot push
  to the repository or when genuine independent review is wanted.

Commit subjects use `<area>: <imperative summary>` and should usually be shorter
than expected. A body is optional. Add one only when the motivation, constraint,
or trade-off would matter to somebody reading the history; do not narrate the
diff or fill out a change checklist.

Examples:

```text
api: reject ambiguous source arguments

release: verify the wheel before publishing it
```

Before a release, verify the built artifact itself in a clean environment. Never
commit credentials or run live-provider tests without an explicit reason.
