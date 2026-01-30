# Architecture Decisions (ADRs)

Purpose: Capture significant technical decisions, alternatives considered, and their consequences. These documents provide historical context and traceability.

How to read:

- Each ADR is numbered and scoped (e.g., command pipeline, telemetry).
- Status indicates whether the decision is accepted, superseded, or proposed.
- Prefer ADRs for rationale; prefer Reference for current factual APIs.

Orientation:

- If you’re new, start with “Architecture at a Glance,” then skim ADR titles here to map the landscape.
- Use ADRs to understand “why,” not “how to.”

See also:

- Architecture Rubric for ongoing design fitness checks
- Deep Dives for formal subsystem specs
- Project History & GSoC for a narrative overview

## Directory

- ADR‑0001: Adopt Asynchronous Handler Pipeline for Pollux Execution — Accepted (2025‑08‑11). Scope: executor/pipeline. Why: immutability, stateless handlers, async throughput.
- ADR‑0002: Hybrid Token Estimation with Provider Adapters and Validation Telemetry — Accepted (2025‑08‑12). Scope: planner/tokens. Why: provider‑agnostic, conservative planning, validation at execution.
- ADR‑0003: Capability‑Based API Handler with Pure Execution State — Accepted (2025‑08‑13). Scope: API handler/adapters. Why: capability protocols, pure state, orthogonal telemetry.
- ADR‑0004: Middleware Pattern for Vendor‑Neutral Rate Limiting — Accepted (2025‑08‑13). Scope: pipeline/middleware. Why: data‑driven constraints, dual limiters, observability.
- ADR‑0005: Two‑Tier Transform Chain for Result Building — Accepted (2025‑01‑11). Scope: result builder. Why: deterministic success, pure transforms, diagnostics.
- ADR‑0006: Telemetry Context and Reporter Protocol — Accepted (2025‑08‑18). Scope: telemetry. Why: no‑op fast path, protocol reporters, scoped metrics.
- ADR‑0007: Configuration Resolution & Immutability — Accepted (2025‑08‑17). Scope: config. Why: resolve‑once, freeze‑then‑flow, profiles/precedence.
- ADR‑0008: Conversation Extension — Accepted (2025‑08‑22). Scope: extension. Why: snapshot facade, `ExecutionOptions`, batch metrics, persistence seams.
- ADR‑0009: Prompting System — Accepted (2025‑08‑23). Scope: planner/prompts. Why: `PromptBundle`, system instruction support, cache determinism.
- ADR‑0010: Hint Capsules → ExecutionOptions — Accepted (2025‑08‑23). Scope: options seam. Why: typed, provider‑neutral controls for estimation/result/cache.
- ADR‑0011: Cache Policy and Planner Simplification — Accepted. Scope: planner/cache policy. Why: first‑turn‑only default, confidence floor, SDK‑free planner.
- DB‑0001: Vectorized Batching & Fan‑out (Historical Design Brief) — Informational (Historical). Scope: vectorization/fan‑out. Why: design brief that informed ADR‑0010 and options seam.

If you’re new, skim titles and dive into ADR‑0001, ADR‑0002, and ADR‑0010 first; then branch into areas of interest.

GSoC note: During GSoC, these ADRs anchored major pivots — adopting the pipeline, hybrid estimation, vendor‑neutral rate limiting, and the options seam. See Project History for a high‑level narrative.
