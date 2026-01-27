# Glossary

This glossary defines key terms used across the codebase and documentation. It’s grouped by area for quick lookup and linked where relevant.

## Core Concepts

- Command: Immutable description of a request (sources, prompts, config). May have typed variants (Initial, Resolved, Planned).
- Source: Structured metadata for an input item (type, identifier, mime, size, content_loader).
- ExecutionPlan: Explicit instructions for API execution (model, parts, config, caching, optional fallback).
- Handler: Stateless component that transforms one Command state into the next.
- GeminiExecutor: Orchestrator that runs a Command through Handlers.
- APIHandler: Handler that executes provider SDK calls and records actual usage.
- Result Builder: Handler that parses outputs, validates schema, and merges telemetry/metrics.
- Result: Unified result type (Success/Failure) used for control flow.

## Estimation & Tokens

- TokenEstimate: Range-based estimate (min/expected/max) with confidence and optional breakdown.
- Estimation Adapter: Provider-specific, pure estimator used by the planner; no SDK calls.

## Testing & CI

- Lane: A curated set of tests exposed as a Makefile target (e.g., `test-smoke`, `test-fast`, `test-pr`, `test-main`). Lanes differ by markers included/excluded, speed, and purpose.
- Marker: A Pytest label used to select or exclude tests (e.g., `unit`, `contract`, `integration`, `characterization`, `workflows`, `slow`, `api`, `security`, `smoke`, `scenario`, `legacy`). See `pyproject.toml` for the authoritative list.
- Characterization test: A golden or snapshot-style test that locks existing behavior to detect regressions. Prefer the `characterization` marker (alias `golden_test` remains for legacy).
- Contract test: Fast, cross-cutting invariants that enforce architectural decisions and safety rails; marked `contract`.
- Smoke tests: Ultra-fast, critical happy-path checks (< 1 minute) intended for quick confidence (`test-smoke`).
- Scenario tests: Curated end‑to‑end flows under `tests/workflows/scenarios/` (opt‑in via `-m scenario`).
- API tests: Tests that require real provider API access; marked `api`. They are opt‑in and collected only when both an API key and `ENABLE_API_TESTS=1` are set.
- Workflows tests: Tests validating CI/CD workflows and repository automation; marked `workflows`.
- Security tests: Secret-handling and security‑critical checks; marked `security`.
- Slow: Marker indicating tests expected to take >1s; excluded from fast lanes.
- Legacy: Marker for quarantined or historical tests retained for reference; not part of normal lanes.
- Progressive testing: A fail‑fast sequence (contracts → unit → characterization) that stops at the first failure; implemented by `make test-progressive`.
- CI lanes: The lane selection CI uses for given events (feature push → `test-fast`, PR → `test-pr`, main → `test-main`, release → `test-main` + optional API). See “Testing Strategy”.
- Coverage threshold: Minimum acceptable coverage for `make test-coverage`, adjustable via `COVERAGE_FAIL_UNDER` (default 40).
- Durations report: Pytest’s slowest test summary shown via `--durations=10`; exposed in `make test-fast-timed`.

## Configuration & Secrets

- GEMINI_API_KEY / POLLUX_API_KEY: Environment variables that hold the provider API key. When both are present, the batch‑specific key takes precedence.
- ENABLE_API_TESTS: Environment flag that must be set (e.g., `ENABLE_API_TESTS=1`) to collect and run tests marked `api`.
