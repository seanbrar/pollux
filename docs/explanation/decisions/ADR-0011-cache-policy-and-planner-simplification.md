# ADR-0011 — Cache Policy, First-Turn-Only, and Planner Simplification

Status: Accepted

Audience: Contributors and extension authors
Impacted Modules/APIs: Planner cache policy resolution, `CachePolicyHint`, `CacheDecision` metadata, API Handler cache fallback/telemetry

Related:

- Architecture at a Glance: explanation/architecture.md
- Architecture Rubric: explanation/architecture-rubric.md
- Concept – Token Counting & Estimation: explanation/concepts/token-counting.md
- Concept – Hint Capsules: explanation/concepts/hint-capsules.md

## Summary

This ADR specifies a simplified, robust caching policy that restores the core architectural principles while improving UX. We adopt Option A with a confidence floor and first-turn-only by default, controlled via a focused `CachePolicyHint`. We also introduce typed policy/decision data, canonicalize threshold resolution, and make responsibilities explicit. The planner returns to being “dumb” and pure; SDK or vendor endpoints are not invoked during planning.

## Current State & Problems

Recent diffs enabled functional improvements (vectorized workloads, better shared cache keys, and a vendor-token integration path), but introduced architectural drift:

- Planner impurity: `planner.py` imported a vendor counter and called into vendor heuristics, violating “no SDK in planning.”
- Increased control-flow complexity: multiple modes, thresholds, and top‑K branches embedded in the planner.
- Responsibility leakage: the planner assembled component weights and duplicated type logic rather than consuming data/breakdowns from adapters.
- API boundary bleed: provider adapter accepted `Source` to inline file content; `api_handler` created `Source` objects to pass provider data.
- UX ambiguity: when caching is enabled but content is “obviously small,” attempting cache creation leads to wasted attempts; skipping can surprise users if not explained.

These changes improved functionality, but regressed against the rubric on Simplicity, Clarity, and Robustness.

## Key Considerations & Boundaries

- Planner must remain pure, provider‑agnostic, and data‑centric. It never calls SDKs or reads content.
- Heuristics are for “obviously small” gating only; precise token accuracy is not a planning goal.
- Caching should be optimistic and graceful: failures do not degrade UX or derail execution.
- Hint capsules are the single interface for extension intent; the core does not grow bespoke flags.
- First turn only by default: most large shared context arrives with the first user prompt. Later attempts are opt‑in via hints.
- Vendor preflight is an optional extension concern, not part of core planning.
- Conversation extension owns long-context packing and any exact token needs.

## Decision (Approach)

We adopt Option A with a confidence floor and first‑turn‑only default, tightened to 5/5 across the rubric via typed data and invariants:

1) Policy as data
   - Add a small `CachePolicyHint` capsule (new), plus a validated `CachePolicy` dataclass resolved from `FrozenConfig` and hints.
   - Fields: `first_turn_only: bool`, `respect_floor: bool`, `conf_skip_floor: float`, `min_tokens_floor: int | None`.

2) Decision as data
   - Introduce a `CacheDecision` struct: `attempt: bool`, `reason: Literal["explicit_disabled","no_shared","reuse_only","first_turn_only","below_floor_high_conf","ok"]`, `floor:int`, `estimate:TokenEstimate | None`, `conf_cut:float`, `first_turn:bool`.
   - Attach the decision to the `ExecutionPlan` (metadata) for transparency and telemetry.

3) First‑turn‑only default
   - Attempt shared cache creation only on turn 1 (history empty), unless `CachePolicyHint(first_turn_only=False)`.

4) Confidence floor skip
   - Skip creation if both are true: `shared_estimate.max_tokens < floor_threshold` and `shared_estimate.confidence >= conf_skip_floor` and `respect_floor=True`.
   - Floor resolution: prefer model capabilities (`explicit_minimum_tokens` → `implicit_minimum_tokens`) else 4096; allow `min_tokens_floor` override.

5) Planner purity restored
   - Remove vendor counting/refinement logic from the planner. Planner computes heuristic token estimates only and decides caching purely from data.

6) API handler fallbacks & clarity
   - On cache create failure (e.g., “too small”), proceed without cache, emitting telemetry (no user‑visible error, no infinite retries).
   - Optional opportunistic creation for vectorized runs is deferred; first‑turn‑only default keeps behavior predictable.

7) Boundary hygiene (optional, but recommended)
   - Add `FileInlinePart` (neutral APIPart) for cache creation payloads.
   - Provider adapters no longer accept `Source` in `_to_provider_part`.

## Intended Outcomes

- Simplicity & Clarity: One small predicate governs cache creation. Decisions are explicit data with stable reasons.
- Robustness: No SDK in planner; invalid states are prevented by invariants and typed policy/decision.
- UX: No surprises (never attempt caching unless enabled). Skips are high‑confidence only and clearly logged/telemetered; users can override via hints.
- Extensibility: Downstream/extension code can change behavior via hints or by owning long‑context/token‑exact logic without touching the core planner.

## Detailed Plan (Decomposed Steps)

Phase 1 — Types and Policy Resolution

- Add `CachePolicyHint` (new) to `pipeline/hints.py`.
- Add `CachePolicy` dataclass and `resolve_cache_policy(config, hints) -> CachePolicy` (new module, e.g., `pipeline/policy/cache_policy.py`). Validate bounds (0 ≤ conf ≤ 1).
- Add `CacheDecision` dataclass (e.g., in `pipeline/policy/cache_policy.py`).

Phase 2 — Planner Simplification

- Remove vendor-token imports and logic from `pipeline/planner.py` (single‑ and vectorized paths).
- Compute `shared_estimate` (history + sources) via adapter (unchanged, pure).
- Resolve `CachePolicy` once and derive `floor_threshold` via a canonical helper using model capabilities with override support.
- Evaluate `first_turn_only` and `respect_floor` predicates. Produce a `CacheDecision` with an explicit `reason`.
- Attach `CacheDecision` to `ExecutionPlan` metadata and create an `ExplicitCachePlan` only if `decision.attempt` is true.
- Enforce invariants in planner (assertions or guarded ValueErrors):
  - If `config.enable_caching=False` then `shared_cache.create=False`.
  - If `reuse_only=True` then `create=False`.
  - If `below_floor_high_conf` and `respect_floor=True`, ensure `attempt=False`.

Phase 3 — API Handler UX & Telemetry

- Consume `CacheDecision` metadata (if present) and emit telemetry/log lines:
  - cache.create.attempted / cache.create.skipped_floor_high_conf / cache.create.succeeded / cache.create.failed
  - Include tags: `floor`, `estimate_expected`, `estimate_max`, `conf`, `reason`.
- On provider “too small” or other cache create failure, proceed without cache and set `retried_without_cache=True` metadata for the call.
- Keep first‑turn‑only behavior (no opportunistic create mid‑batch by default). Optionally add a future flag to enable it.

Phase 4 — Boundary Hygiene (Optional, High-Value)

- Add `FileInlinePart(mime_type: str, data: bytes)` to `core/types.py` and union `APIPart`.
- Update `adapters/gemini.py._to_provider_part` to map `FileInlinePart` to provider blobs; remove acceptance of `Source`.
- In `api_handler.py`, when creating cache, convert `FilePlaceholder` to `FileInlinePart` (one guarded read) instead of `Source`.

Phase 5 — Documentation & Fitness Tests

- Docs: Update `hint-capsules.md` with `CachePolicyHint` semantics and examples.
- Docs: Update `token-counting.md` to reassert “no SDK in planning,” and describe the floor rule.
- Docs: Reference this ADR in `architecture.md` and the Command Pipeline concept.
- Fitness tests (lightweight):
  - Ensure planner does not import vendor modules.
  - Ensure `history != 0` yields `first_turn_only` skip unless overridden.
  - Ensure `enable_caching=False` → no create, regardless of hints.

## Major/Affected Files

- Add: `src/pollux/pipeline/policy/cache_policy.py` (policy + decision + helpers)
- Update: `src/pollux/pipeline/hints.py` (add `CachePolicyHint`)
- Update: `src/pollux/pipeline/planner.py` (remove vendor logic; add policy/decision; first‑turn‑only + floor)
- Update: `src/pollux/pipeline/api_handler.py` (fallback UX + telemetry; consume decision)
- Optional Add: `src/pollux/core/types.py` (`FileInlinePart`)
- Optional Update: `src/pollux/pipeline/adapters/gemini.py` (support `FileInlinePart`, drop `Source` acceptance)
- Docs: this ADR; update `concepts/hint-capsules.md`, `concepts/token-counting.md`, and cross‑links in `architecture.md`.

## Rationale (Rubric Mapping)

- Simplicity & Elegance: Planner contains a single, explicit predicate and produces a small data decision. No vendor logic in planning.
- Data‑Centricity: Policy and decision are rich data; planner behavior is a pure transformation of state → state.
- Clarity & Explicitness: Decision reasons are explicit and stable; telemetry mirrors them. “What you see is what you get.”
- Robustness: Invariants prevent invalid states; SDK-free planner eliminates a class of failures; conservative thresholds avoid surprises.
- DX/Testability: Pure functions for policy resolution and decision; trivial unit tests; zero mocks.
- Extensibility: Extensions adjust via hints or own long‑context logic; core remains stable.

## Risks & Mitigations

- User confusion when caching is enabled but skipped: Mitigate with clear telemetry/logs and `CachePolicyHint(respect_floor=False)` override.
- Threshold drift across models: Use capability‑driven floors; document override via `min_tokens_floor`.
- Slight increase in policy surface: Contained within a small typed module; defaults keep behavior predictable.

## Operational Notes

- Cache creation on high‑fan‑out, low‑payload workloads can add avoidable cost/latency. Prefer `CachePolicyHint(reuse_only=True)` or `respect_floor=True` with an appropriate `min_tokens_floor` to suppress creation in those scenarios.

## Acceptance Criteria

- Planner contains no vendor imports and no file reads.
- `CacheDecision` present on plans with a clear `reason` and correct `attempt` flag.
- First‑turn‑only behavior observed by default; can be overridden by `CachePolicyHint(first_turn_only=False)`.
- Floor skip occurs only when high confidence and below threshold; override works.
- API handler handles cache create failure gracefully with telemetry, not errors.

## Future Work (Non‑Blocking)

- Optional vendor preflight extension (API handler seam) for near‑threshold scenarios — not part of core planning.
- Optional opportunistic cache creation mid‑vectorized batch controlled by a policy flag.
- Enrich `TokenEstimate.breakdown` labels and propagate component metadata for extension observability.
