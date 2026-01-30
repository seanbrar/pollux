# ADR‑0010 — Hint Capsules (Extensions → Core)

**Status:** Accepted (updated: ExecutionOptions preferred)
**Date:** 2025‑08‑23
**Scope:** `planner`, `cache_stage`, `api_handler`, `result_builder`; option types in `core/execution_options.py`.
**Audience:** Extension authors and contributors
**Impacted Modules/APIs:** `ExecutionOptions` (estimation/cache/result), legacy hints, planner/cache/api/result interpretation

## Context

We need a provider‑neutral way for extensions to express advanced intent to the pipeline (cache reuse identity, conservative token bounds, extraction preferences) without:

* introducing provider branches into core,
* changing handler responsibilities, or
* relying on implicit registry side‑effects.

At the same time, we must preserve **radical simplicity**: *less surface, more leverage*.

## Decision

Adopt **Hint Capsules** as a small union of frozen dataclasses carried initially on `InitialCommand.hints`, then evolve to a typed, structured **ExecutionOptions** field on `InitialCommand`. Handlers prefer options over hints where both are present:

* **Planner** reads `ExecutionOptions.estimation` (preferred) to adjust `TokenEstimate.max_tokens` (pure transform). Legacy `EstimationOverrideHint` remains supported.
* **Cache Stage** reads `ExecutionOptions.cache`/`cache_policy` (preferred) to apply deterministic cache identity and creation policy at execution time.
* **API Handler** performs a best‑effort read of `ExecutionCacheName` (legacy) and treats it as explicit cache intent for resilience: on a cache‑related failure it retries once without cache (same behavior as when a cache plan/name was applied).
* **Result Builder** optionally biases transform order with `ExecutionOptions.result` (preferred).

Unknown hints are ignored. No handler gains provider‑specific code. Options are provider‑neutral and keep behavior explicit.

## Consequences

### Positive

* Single, explicit seam for extension intent; improved auditability and testability. Options make configuration IDE‑discoverable.
* No new control flow; handlers still do one thing each.
* Conservative, fail‑soft behavior: system remains correct even if hints are missing or partially supported.
* Observability: handlers may emit telemetry about hint usage for audit purposes.

### Negative / Risks

* Heterogeneous provider support means some options/hints become no‑ops.
* Temptation to add too many knobs. Mitigation: keep `ExecutionOptions` small and neutral; push provider details behind adapters.

## Alternatives considered

1. **Registry‑only signaling**

   * *Pros*: zero API change.
   * *Cons*: implicit, hard to audit, limited beyond caching.

2. **PlanDirectives DSL**

   * *Pros*: very explicit, audit‑friendly.
   * *Cons*: overkill for the goal; increases surface and maintenance.

3. **Executor‑level transient bag**

   * *Pros*: no type change on `InitialCommand`.
   * *Cons*: action‑at‑a‑distance risk; weaker audit trail unless duplicated into telemetry.

## Detailed design (updated)

* Add `InitialCommand.options: ExecutionOptions | None = None` and prefer it over hints when present. Keep `InitialCommand.hints` temporarily for compatibility.
* Planner: read `ExecutionOptions.estimation`; do not interpret cache options (CacheStage handles caching).
* Cache Stage: interpret `ExecutionOptions.cache`/`cache_policy`, derive deterministic identity, reuse/create as capabilities allow; update plan immutably.
* API Handler: treat `ExecutionCacheName` (legacy) as best‑effort override; derive a single `CacheIntent` struct to simplify resilience and telemetry.
* Result Builder: bias transform order when `ExecutionOptions.result.prefer_json_array` is set; Tier‑2 fallback guarantees success.

## Invariants

* `options is None` and `hints is None` ⇒ identical behavior and outputs.
* Planner remains the **only** place that computes token estimates.
* API Handler remains the **only** place that talks to adapters; the only change to retries is a single no‑cache retry when an exec‑time cache override is provided (same as with an explicit cache plan).
* Result Builder always returns success via Tier‑2 fallback.

## Migration & rollout

1. Introduce `ExecutionOptions` and thread through planner/cache stage/result builder. Prefer options when both options and hints are present.
2. Keep legacy hints functioning for one pre‑release cycle; mark them as deprecated in docs.
3. Update extensions to populate `ExecutionOptions` instead of hints.
4. Add/maintain tests for both paths during transition.

Rollback: if options adoption causes issues, handlers can temporarily fall back to legacy hints. Both approaches are data‑only and do not alter core control flow.

## Open questions / follow‑ups

* Add `BatchHint` once vectorized adapters surface per‑prompt outputs/metrics consistently.
* Consider `ExecAdapterHint` when providers expose stable, documented keys; keep them namespaced.
* Telemetry integration: handlers emit minimal hint usage metrics for audit purposes.

## References

* Command Pipeline & Prompting docs
* ADR‑0008 Conversation Extension
* DB‑0001 Vectorization and Fan‑out (Historical Design Brief)

## History

This ADR evolved from an earlier focused design brief on vectorization and fan‑out. That brief (now documented as DB‑0001) clarified the need for a neutral, typed seam to communicate planner/result/cache intent from extensions into core without provider coupling. The seam materialized as `ExecutionOptions` replacing ad‑hoc “hint capsules”.
