# ADR-0002: Hybrid Token Estimation with Provider Adapters and Validation Telemetry

**Date:** 2025-08-12
**Status:** Accepted
**Tags:** planning, estimation, adapters, telemetry, vendor-neutral
**Audience:** Contributors and adapter authors
**Impacted Modules/APIs:** Execution Planner, token estimation adapters, telemetry validation in API Handler

---

## Context

The planner must make batching and caching decisions **before** contacting any provider SDK. Vendor counters can be biased by content type (e.g., images vs. video), leading to mis-sized plans and avoidable failures.

Prior approaches coupled token logic with client/config code and occasionally relied on vendor counters inline, creating:

- Tight coupling to provider SDKs
- Hidden sequencing between planning and execution
- Fragile tests that depended on mocked SDK behavior
- Difficulty detecting and correcting bias drift

---

## Decision

Adopt a **hybrid estimation model** that combines:

1. A **pure estimation pipeline** returning `TokenEstimate {min, expected, max, confidence, breakdown}`
2. **Provider-specific estimation adapters** encapsulating heuristics and compensation (e.g., content-type bias factors)
3. **Validation telemetry** recorded at execution time (in the API Handler) to measure accuracy and detect drift

**Key properties**:

- Estimation occurs in the **Execution Planner** (no SDK calls)
- Provider quirks are confined to **adapters** (planner remains provider-agnostic)
- Planning uses **conservative policies** (e.g., `max_tokens` for cache/batch gating)
- Actual usage is **observed, not fed back** during the same run

---

## Consequences

**Positive**:

- **Simplicity & testability:** Estimation is pure/deterministic; easy unit tests without mocks.
- **Vendor neutrality:** New providers are implemented as new adapters.
- **Safety:** Conservative bounds reduce overflows and cache misses.
- **Observability:** Accuracy ratios and in-range checks reveal drift.

**Negative / Trade-offs**:

- **Manual tuning:** Bias factors and heuristics require periodic review.
- **Overestimation cost:** Conservative bounds may slightly reduce batch density.
- **Two-phase mental model:** Teams must understand planning vs. post-execution validation.

---

## Alternatives Considered

- **Rely on provider counters only:** Easiest, but biases lead to brittle planning.
- **Single-phase exact accounting:** Requires SDK calls in planning; violates architecture constraints.
- **Global heuristic with no adapters:** Simpler but worse fit for multi-vendor futures.

---

## Implementation Notes (non-normative)

- **Adapters:** One per provider (e.g., Gemini, OpenAI, Anthropic), versioned bias tables (e.g., `v1_august_2025`).
- **Aggregation:** Sum bounds across sources; reduce confidence for mixed content; keep per-source breakdown.
- **Planner policy:** Use `max_tokens` for gating (caching, batch size), `expected_tokens` for secondary UX estimates where appropriate.
- **Telemetry:**
  - Planning: `token_estimation.estimate.*` (expected/max/confidence/breakdown)
  - Execution: `token_validation.*` (actual_tokens, accuracy_ratio, in_range)

---

## Migration

- Move token logic out of client/config code into the planner via adapters.
- Keep SDK usage in API Handler; add validation metrics there.
- Update tests to assert estimator determinism and policy behavior (e.g., conservative gating).

---

## References

- [Concept – Token Counting & Estimation](../concepts/token-counting.md)
- [Concept – Command Pipeline](../concepts/command-pipeline.md)
- [Deep Dive – Command Pipeline Spec](../deep-dives/command-pipeline-spec.md)
- [Deep Dive – Token Counting Calibration](../deep-dives/token-counting-calibration.md)
- [Architecture at a Glance](../architecture.md)

---

## Status and validation targets

- Status: Implemented on a separate branch (adapters under `pipeline/tokens/adapters/`, planner integration under `pipeline/planner.py`).
- Initial validation targets:
  - ≥95% of actual token usage within `[min, max]` range over evaluation corpus
  - Misses skew toward over-estimation
  - Median `accuracy_ratio` drift ≤10% across two releases

## Versioning policy

- Bias tables are versioned (e.g., `GeminiBiases.v1_august_2025`).
- Update the default alias (`latest`) when drift criteria are met and tests pass.
