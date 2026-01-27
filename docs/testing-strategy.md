# Testing Strategy

Last reviewed: 2025-09

Audience: contributors and maintainers who want to understand why tests run when they do, what each lane validates, and how CI chooses suites. If you just want to run tests locally, see How‑to → [Testing](how-to/testing.md).

## Cadence at a Glance

| Event | Suite | Target | Validates |
| --- | --- | --- | --- |
| Feature push | `make test-fast` | < 30s | Contracts, unit, integration, workflows, security (no `slow`/`api`/`characterization`) |
| Draft PR | `make test-fast` (+ DEBUG) | < 30s | Same as feature push with verbose logs |
| Ready PR | `make test-pr` | < 2 min | Progressive core + integration + workflows |
| Main merge | `make test-main` | < 5 min | Everything incl. coverage |
| Release | `make test-main` + API | < 10 min | Full suite plus opt‑in API checks |

!!! note "Notes"

    - API tests are opt‑in and run only when both an API key and an explicit enable flag are set. Set either `GEMINI_API_KEY` or `POLLUX_API_KEY` and also `ENABLE_API_TESTS=1`. Keep them off for regular CI to avoid flakiness and rate limits. Running API tests may incur costs and trigger rate limits—enable them intentionally.
    - Coverage HTML reports are written to `coverage_html_report/` during `make test-coverage` and on the `make test-main` lane.

## Rationale

- Optimize for fast local iteration while guarding key architecture decisions early (contracts).
- Escalate breadth and depth as code approaches merge: smoke → fast → progressive → full with coverage.
- Keep expensive lanes (slow/API) opt‑in to preserve velocity and stability.

## CI Selection Rules

CI picks a lane based on the event type:

- Feature branches: runs `test-fast` for quick feedback across core paths.
- Draft PRs: runs `test-fast` with `TEST_LOG_LEVEL=DEBUG` for richer logs.
- Ready PRs: runs `test-pr` (progressive fail‑fast + integration + workflows).
- Main: runs `test-main` (all tests with coverage reporting).
- Releases: run `test-main`; optionally enable API checks by setting `GEMINI_API_KEY` (or `POLLUX_API_KEY`) and `ENABLE_API_TESTS=1`.

## Progressive Testing (Fail‑Fast)

`make test-progressive` runs tests in order of importance and stops at first failure:

1. Architectural contracts (fast invariant guards)
2. Unit tests (core behaviours)
3. Characterization (golden) tests (behaviour locks)

This catches systemic issues early while still exercising behaviour locks when core invariants hold.

## Lanes and What They Cover

- `test-smoke`: curated, ultra‑fast happy‑path checks for the most critical features.
- `test-fast`: contracts + unit + integration + workflows + security; excludes `slow`, `api`, and `characterization`.
- `test-pr`: `test-progressive` plus integration and workflow tests.
- `test-main`: all non‑API tests plus coverage; includes `test-all` and `test-coverage`.

See How‑to → [Testing](how-to/testing.md) for exact commands and additional granular targets (unit, integration, workflows, etc.). For taxonomy and markers, see Test layout and markers. See Explanation → [Glossary](explanation/glossary.md) for terms like “lanes”, “markers”, and “characterization”.

## Customization Levers

- Markers: adjust what belongs in fast vs. slow lanes (`slow`, `api`, `characterization`, etc.).
- Lanes: tune Makefile targets to add/remove markers or timing flags.
- CI: encode selection logic in workflow conditions; introduce matrices if needed.

## Benefits

- Fast feedback on feature branches (~30s typical).
- Early failure on architectural violations (contracts first).
- Resource‑aware: slow and API checks are opt‑in.
- Clear escalation toward merge and release.
- Debug‑friendly: draft PRs include verbose logging.

## Related

- How‑to: Testing: [how-to/testing.md](how-to/testing.md)
- Test layout and markers: [tests.md](tests.md)
- Contract‑First Testing (concepts): [explanation/concepts/contract-first-testing.md](explanation/concepts/contract-first-testing.md)
