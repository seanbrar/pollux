# Hint Capsules → Execution Options

> Status: Updated — ExecutionOptions preferred (hints temporarily supported)
> **Audience:** Contributors and advanced users
> **Position:** Explanation (what/why). Not an API reference or how‑to.
> **Scope:** Planner/API Handler/Result Builder touchpoints enabling *extension‑provided* hints in a provider‑neutral, fail‑soft way.

---

## Purpose

Hint Capsules were introduced as a tiny, immutable way for extensions to express intent to the core pipeline without coupling the core to any domain (e.g., "conversation"). As the library matured, we evolved this seam into a single, typed object: **ExecutionOptions**. Options make advanced behavior discoverable and IDE‑friendly while preserving the same data‑centric, fail‑soft philosophy.

Supported intent (preferred via ExecutionOptions; legacy hints still work for now):

* Cache identity/policy (CacheOptions, CachePolicyHint) → `ExecutionOptions.cache`, `ExecutionOptions.cache_policy` (consumed at CacheStage).
* Estimation override (EstimationOverrideHint) → `ExecutionOptions.estimation` (consumed at Planner).
* Result transform bias (ResultOption) → `ExecutionOptions.result` (consumed at ResultBuilder).
* Execution‑time cache name override (ExecutionCacheName) → still provided as a legacy hint for now (read at APIHandler); will be revisited.

> Future (non‑breaking) additions may include `BatchHint` and `ExecAdapterHint` once adapters/telemetry warrant them.

---

## Why this exists (and what it replaces)

Without a neutral hint seam, extensions either:

* overreach into handler internals, or
* rely on opaque registries/side‑effects, or
* fork provider adapters.

**Hint Capsules** provide one *explicit*, *typed* place to express: “I’d prefer to reuse this cache identity,” “widen max tokens conservatively,” or “prefer JSON array extraction,” while preserving the Command Pipeline’s invariants and **single SDK seam**.

---

## Design tenets (Rubric alignment)

* **Radical Simplicity:** one optional field `InitialCommand.options: ExecutionOptions | None` (preferred). Legacy `InitialCommand.hints` remains temporarily supported.
* **Data over Control:** hints are *data*, consumed by existing stages via small, pure transforms.
* **Explicit over Implicit:** unknown hints are ignored; no hidden globals or ambient state.
* **Immutability:** hints travel with the immutable command; handlers remain stateless.
* **Single Provider Seam:** provider‑specific details remain inside adapters; core surfaces only neutral shapes.
* **Audit‑grade:** telemetry may record “hints seen,” but behavior never *depends* on undeclared state.

---

## Conceptual model

```text
InitialCommand(options?) ──► Execution Planner ──► Cache Stage ──► API Handler ──► Result Builder
         │                      │ (estimation)        │ (cache policy,        │ (best‑effort         │ (transform
         │                      │                     │ identity)             │ cache override)      │ preference)
         ▼                      ▼                     ▼                      ▼                      ▼
     Fail‑soft             Pure estimation;      Provider‑neutral;       Same resilience;      Tier‑1 bias only;
  (options optional)       no provider logic     reuse/create handled    retries unchanged     Tier‑2 fallback unchanged
```

### Options and legacy hints

* **Cache (CacheOptions/CachePolicyHint → ExecutionOptions.cache/cache_policy)**

  * Fields mirror the underlying hint types.
  * **Cache Stage:** interprets cache identity/policy at execution time (provider‑neutral), applies deterministic name, and updates the execution plan.
  * **API Handler:** unchanged; writes best‑effort cache metadata to registry for observability.

* **Estimation (`ExecutionOptions.estimation`)**

  * Fields: `widen_max_factor: float = 1.0`, `clamp_max_tokens: int | None = None`.
  * **Planner:** Applies a pure transform to `TokenEstimate.max_tokens` (widen then clamp). No runtime/provider coupling.

* **Result (`ExecutionOptions.result`)**

  * Fields: `prefer_json_array: bool = False`.
  * **Result Builder:** Optionally biases Tier‑1 transform order (e.g., bubble `json_array`); Tier‑2 minimal projection guarantees success regardless.

* **ExecutionCacheName (legacy)**

  * Fields: `cache_name: str`.
  * **API Handler:** Best‑effort override of cache name at execution time. On cache‑related failure, triggers a single no‑cache retry. May be revisited as part of a future options extension.

* **`CachePolicyHint`**

  * Fields: `first_turn_only: bool | None = None`, `respect_floor: bool | None = None`, `conf_skip_floor: float | None = None`, `min_tokens_floor: int | None = None`.
  * **Planner:** Adjusts the resolved cache planning policy (pure data) used to produce a `CacheDecision`. Defaults are conservative: first‑turn‑only enabled, confidence floor respected, and floor sourced from model capabilities unless overridden.
  * **Semantics:**
    * First‑turn‑only: create shared cache only when history is empty (turn 1) unless set to False.
    * Confidence floor: skip creation when `estimate.max_tokens < floor` AND `estimate.confidence ≥ conf_skip_floor` AND `respect_floor=True`.
    * Floor resolution: `explicit_minimum_tokens` → `implicit_minimum_tokens` from model capabilities; override via `min_tokens_floor` when needed.
  * **API Handler:** Emits telemetry reflecting `CacheDecision`; failures to create cache are non‑fatal (fall back to no cache).

* **`CachePolicyHint`**

  * Fields: `first_turn_only: bool | None = None`, `respect_floor: bool | None = None`, `conf_skip_floor: float | None = None`, `min_tokens_floor: int | None = None`.
  * **Planner:** Adjusts the resolved cache planning policy (pure data) used to produce a `CacheDecision`. Defaults are conservative: first‑turn‑only enabled, confidence floor respected, and floor sourced from model capabilities unless overridden.
  * **Semantics:**
    * First‑turn‑only: create shared cache only when history is empty (turn 1) unless set to False.
    * Confidence floor: skip creation when `estimate.max_tokens < floor` AND `estimate.confidence ≥ conf_skip_floor` AND `respect_floor=True`.
    * Floor resolution: `explicit_minimum_tokens` → `implicit_minimum_tokens` from model capabilities; override via `min_tokens_floor` when needed.
  * **API Handler:** Emits telemetry reflecting `CacheDecision`; failures to create cache are non‑fatal (fall back to no cache).

> No hint *requires* handler changes elsewhere; the control path and error semantics remain the same.

---

## Invariants & properties

* **I1 — No‑op by default:** `options=None` (and `hints=None`) yields identical behavior and outputs.
* **I2 — Planner owns estimation:** overrides are planner‑scoped transforms; API handler only validates/attaches usage telemetry.
* **I3 — Deterministic caching:** `ExecutionOptions.cache` (or legacy cache hint) yields deterministic identity; reuse‑only never hard‑fails.
* **I4 — Provider neutrality:** no provider branches in core; adapters may ignore namespaced details until supported (future additions only).
* **I5 — Guaranteed results:** Result Builder's Tier‑2 fallback keeps the system fail‑soft even with misleading or partial hints.
* **I6 — Observability:** Hints may generate telemetry data for audit and debugging purposes without affecting core behavior.

---

## Interaction with other concepts

* **Command Pipeline:** Hints *decorate* the initial command; all handler responsibilities remain intact.
* **Prompting System:** Unaffected. Prompt assembly precedes hint consumption; cache keys still include system text when present.
* **Vectorization & Fan‑out (DB‑0001, historical brief):** `BatchHint` is explicitly out of scope for the minimal pass; the seam is compatible when added.

---

## Rationale & trade‑offs

* **Why a single hints field?** It centralizes advanced intent in one predictable place, improving discoverability and testability.
* **Why fail‑soft?** Extensions evolve faster than core; ignoring unknown hints avoids coupling and preserves stability.
* **Why not registry‑only?** Registries alone are implicit. Hints keep decisions explicit while still allowing registries to assist (e.g., cache name reuse).
* **Why not a DSL?** Too heavy for the goal; Hint Capsules are a *toe‑hold* for power without extra concepts.

---

## Minimal type sketch (illustrative)

```py
@dataclass(frozen=True)
class ExecutionOptions:
    cache_policy: CachePolicyHint | None = None
    cache: CacheOptions | None = None
    result: ResultOption | None = None
    estimation: EstimationOverrideHint | None = None
```

> Real API signatures live in the code; this is not a reference spec.

---

## Examples (high‑level intent)

* **Conversation cache identity**: Extension maps `ConversationState.cache.key` → `ExecutionOptions.cache.deterministic_key` so CacheStage applies an explicit identity; providers that support explicit caching reuse it deterministically.
* **Tight cost guardrails**: An evaluation tool sets `EstimationOverrideHint(widen_max_factor=1.1, clamp_max_tokens=16000)` for safer rate‑limit planning.
* **JSON‑first extraction**: A structured data workload sets `ResultOption(prefer_json_array=True)` to bias Tier‑1 extraction; fallback keeps results stable if the model outputs text.

---

## Risks & mitigations

* **Over‑hinting:** treat hints as *preferences*, not guarantees. Mitigation: document fail‑soft semantics and keep planner policies conservative.
* **Adapter heterogeneity:** not all providers support explicit caching/telemetry. Mitigation: hints are optional; registries and fallback paths remain.
* **Surface creep:** keep `ExecutionOptions` small and neutral; avoid growing handler responsibilities.

---

## Related documents

* Command Pipeline – Conceptual Overview (`docs/explanation/concepts/command-pipeline.md`)
* Prompting System – Conceptual Overview (`docs/explanation/concepts/prompting.md`)
* ADR‑0001 Command Pipeline (`docs/explanation/decisions/ADR-0001-command-pipeline.md`)
* ADR‑0008 Conversation Extension (`docs/explanation/decisions/ADR-0008-conversation.md`)
* DB‑0001 Vectorization and Fan‑out (Historical Design Brief) (`docs/explanation/decisions/DB-0001-vectorization-and-fanout.md`)

### Using ExecutionOptions (example)

```py
from pollux import types
from pollux.core.execution_options import CacheOptions, CachePolicyHint, ResultOption, EstimationOverrideHint

opts = types.ExecutionOptions(
    cache_policy=CachePolicyHint(first_turn_only=True, respect_floor=True),
    result=ResultOption(prefer_json_array=True),
    estimation=EstimationOverrideHint(widen_max_factor=1.1, clamp_max_tokens=16000),
)

cmd = types.InitialCommand.strict(
    sources=(types.Source.from_text("hello"),),
    prompts=("Summarize",),
    config=resolved_config,
    options=opts,
)
```

Most users can use the high‑level helpers (`run_simple`/`run_batch`) which construct appropriate `ExecutionOptions` from friendly parameters like `cache=` and `prefer_json`.
