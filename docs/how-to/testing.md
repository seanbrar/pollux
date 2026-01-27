# Testing

Use the Makefile targets for a consistent experience.

## Quick start

```bash
make install-dev        # Install dev deps
make test               # Unit + golden tests (no coverage)
make test-coverage      # All tests with coverage report
make test-all           # Unit + characterization + integration + workflows (non-API)
```

## Granular suites

```bash
make test-unit          # Unit tests only
make test-golden-files  # Golden file regression tests
make test-integration   # Integration tests (skips if semantic-release missing)
make test-workflows     # Workflow configuration tests
make test-api           # API tests (require GEMINI_API_KEY and ENABLE_API_TESTS=1)
```

Notes:

- API tests are opt-in and require an API key and an explicit enable flag. Set `GEMINI_API_KEY` (or `POLLUX_API_KEY`) and `ENABLE_API_TESTS=1`. Running API tests may incur costs and be subject to rate limits—enable them intentionally.
- Some workflow-related tests rely on `semantic-release`; those individual tests will skip gracefully if it is not installed.

Success checks:

- Coverage: after `make test-coverage`, open `coverage_html_report/index.html`.
- API collection: with both `GEMINI_API_KEY`/`POLLUX_API_KEY` and `ENABLE_API_TESTS=1` set, tests marked `api` are collected and run; otherwise they are auto‑skipped.
- Timings: use `make test-fast-timed` to print slowest tests.

## Suites overview

- characterization: golden-file behavioral tests
- workflows: end-to-end pipeline/workflow behavior
- unit: small, focused units

 See Explanation → Contract-First Testing for methodology and invariants. For terminology like “lanes”, “markers”, and “characterization”, see Explanation → Glossary.

Last reviewed: 2025-09
