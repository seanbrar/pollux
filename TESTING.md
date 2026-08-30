# Testing Pollux

Tests are organized around behavior that users or provider adapters can
observe. Add a test where a regression would cross a boundary; do not mirror
the source tree or test an implementation detail merely because it exists.

## Commands

Run a focused test while iterating:

```bash
uv run pytest tests/interaction/test_run_frontdoor.py -v
uv run pytest tests/providers/test_gemini_contract.py -v
```

Run the complete local gate before committing non-trivial work:

```bash
just check
```

That formats and lints Python and Markdown, type-checks the project, and runs
the non-networked test suite. Build documentation separately when it changes:

```bash
just docs-build
```

## Test Areas

- `tests/interaction/` covers the public interaction types and execution
  behavior.
- `tests/providers/` covers request compilation, response extraction, and
  provider-specific capability contracts without live calls.
- `tests/pipeline/` covers public entry points across configuration, caching,
  uploads, retries, continuation, and deferred delivery.
- `tests/test_config.py` and `tests/test_source.py` cover construction and
  validation at those public boundaries.
- `tests/test_cookbook.py` and `tests/test_cookbook_contract.py` keep runnable
  examples aligned with the library.
- `tests/test_api.py` contains opt-in calls to real providers.

Put a regression test at the narrowest area that still observes the behavior a
caller relies on. Prefer a contract test over several tests of private helpers.

## Live Provider Tests

API tests require both a provider credential and an explicit opt-in:

```bash
ENABLE_API_TESTS=1 uv run pytest -m api -v
```

They must skip cleanly without credentials. Keep assertions tolerant of normal
model variation: verify protocol behavior, structure, ordering, or capability
handling rather than exact prose.

## Environment Isolation

The default fixtures clear provider credentials and isolate dotenv behavior.
Read `tests/conftest.py` before changing credential or environment tests. Tests
that intentionally exercise the ambient environment must opt in with the
appropriate marker.

## Deciding What to Test

Add or change a test when behavior changes. A separate test is usually not
useful when the design makes the failure impossible, an existing boundary test
already observes it, the code only delegates to an already-tested path, or the
change affects documentation or formatting alone.

Make that judgment from the actual change. Test counts, coverage percentages,
and named methodologies are not substitutes for deciding whether a regression
would matter.
