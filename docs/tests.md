# Test Suite Reference

Last reviewed: 2025-09

Audience: contributors and maintainers working on tests. If you only need to run tests, see How‑to → [Testing](how-to/testing.md). For terminology (lanes, markers, characterization, smoke), see Explanation → [Glossary](explanation/glossary.md).

> Goal: Make the suite easy to discover, fast to iterate on, and predictable in CI.

## Layout

Typical layout (may vary slightly by domain maturity). Tests generally mirror the `src/pollux/*` domains inside each test type:

```text
tests/
  contracts/{core,config,extensions}
  unit/{config,pipeline,extensions,core,adapters,templates}
  integration/{pipeline,config}
  characterization/{pipeline,extensions,core}
  workflows/{scenarios,...}
  performance/
```

- Keep tests small and focused. Prefer `unit` and `contract` for fast guards; use `integration` for cross‑component behaviour.
- Characterization (golden) tests lock behaviour; use sparingly to avoid brittle coupling.

### Fixtures and Builders

- Centralized fixtures live under `tests/fixtures/` and are auto‑loaded via `pytest_plugins` in `tests/conftest.py`.
- Current modules: `core.py` (env, logging, hooks), `pipeline.py` (executor/client shims), `templates.py` (Jinja/changelog), `workflows.py` (CI repo/workflows).
- Domain‑specific extras can still live in scoped `conftest.py` files (e.g., `tests/unit/extensions/conftest.py`). Keep them tiny.
- Builders (where applicable) help keep tests declarative (e.g., `tests/unit/extensions/_builders.py`).

Note: Workflow execution tests that use `act` are marked `integration`/`slow` and auto‑skip if `act` or Docker are unavailable locally.

## Markers

- `unit`: Unit tests (fast). Default lane for most tests.
- `contract`: Architectural contracts and invariants (fast, cross‑cutting guards).
- `integration`: Cross‑component integrations (may be slow). Avoid external I/O.
- `characterization` and `golden_test`: Behaviour locks and golden file tests (fast). Prefer `characterization` going forward.
- `workflows`: CI/CD and repository automation tests.
- `security`: Secret handling and security‑critical tests.
- `slow`: > 1s runtime; excluded from fast lanes.
- `api`: Requires external API access (opt‑in; excluded from CI by default).
- `smoke`: Ultra‑fast, critical happy‑path checks (< 1m). Used by `make test-smoke`.
- `scenario`: Curated end‑to‑end scenarios under `tests/workflows/scenarios/`.

Register or adjust markers in `pyproject.toml` under `[tool.pytest.ini_options].markers`.

<!-- markdownlint-disable MD046 -->
!!! note "Running API tests"

    API tests are opt‑in and will be collected and executed only when you set an API key and explicitly enable them. Set either `GEMINI_API_KEY` or `POLLUX_API_KEY` and also `ENABLE_API_TESTS=1`. Running API tests may incur costs and be subject to provider rate limits—enable them intentionally.
<!-- markdownlint-enable MD046 -->

## Lanes (Make targets)

- `make test-smoke`: Curated subset to validate critical paths quickly.
- `make test-fast`: Contracts + unit + integration + workflows + security; excludes `slow`, `api`, and `characterization`.
- `make test`: Unit + characterization (goldens) when present; local default.
- `make test-coverage`: Full suite with coverage report in `coverage_html_report/`.

See Explanation → [Testing Strategy](testing-strategy.md) for CI lanes used on PRs and `main` (`test-pr`, `test-main`).

<!-- markdownlint-disable MD046 -->
!!! tip "Tips"

    - Control verbosity: `TEST_LOG_LEVEL=DEBUG make test-fast`.
    - Control parallelism: set `PYTEST_PARALLEL="-n auto"` (default) or `PYTEST_PARALLEL=""` to disable.
    - Coverage threshold: set `COVERAGE_FAIL_UNDER` (default 40) for `make test-coverage`.
    - Performance: `make test-fast-timed` prints the 10 slowest tests.
<!-- markdownlint-enable MD046 -->

## Selecting tests with markers

Examples

```bash
# Unit tests only
pytest -m "unit"

# Fast dev set: contracts + unit (no slow)
pytest -m "(contract or unit) and not slow"

# Integration without slow workflows
pytest -m "integration and not slow"

# Scenarios (opt-in)
pytest -m "scenario"
```

## Adding a test

1. Choose the smallest effective type (`unit` > `contract` > `integration`).
2. Place under the matching domain folder (e.g., `tests/unit/pipeline/`).
3. Add precise markers; prefer module‑level `pytestmark = pytest.mark.unit`.
4. Use shared fixtures from `tests/fixtures/*` (or a small domain `conftest.py`) and avoid ad‑hoc duplicates.
5. Keep runtime low; mark expensive cases as `slow`.

## Scenarios

Scenario tests live in `tests/workflows/scenarios/`. Each scenario includes:

- Preconditions and configuration (explicit inputs under `test_files/` when possible).
- Expected outputs (golden artefacts) and telemetry assertions.
- Setup/teardown helpers to keep assertions focused.

Run with `pytest -m "scenario"` or include in nightly CI.

## Related

- How‑to: Testing: [how-to/testing.md](how-to/testing.md)
- Explanation: Testing Strategy: [testing-strategy.md](testing-strategy.md)
- Concepts: Contract‑First Testing: [explanation/concepts/contract-first-testing.md](explanation/concepts/contract-first-testing.md)
