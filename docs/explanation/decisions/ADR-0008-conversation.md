# ADR-0008 — Conversation Extension

**Status:** Accepted
**Date:** 2025-08-22
**Scope:** `src/pollux/extensions/conversation/*`
**Audience:** Extension authors and application developers
**Impacted Modules/APIs:** Conversation extension (`Conversation`, `ConversationState`, `ConversationStore`), `ExecutionOptions` usage, `GeminiExecutor` entry seam

---

## Context

We need a **multi‑turn conversation** API that delivers:

* **Radical simplicity (UX/DX):** trivial `.ask()` chains and loop‑free multi‑step flows.
* **Determinism & immutability:** no in‑place mutation; reproducible results; typed command states preserved.
* **Good citizen** behavior: strict separation from file I/O; no leakage into core pipeline handlers.
* **Audit‑grade observability:** token/cost metrics, drift tracking, and reproducible config snapshots.
* **Flexibility:** easy cache reuse across turns, source edits mid‑conversation, batch execution modes.

This API is an **extension**, not part of core architecture. It must consume only public core types and the single executor seam, serving as a reference for how to build extensions aligned with the architecture rubric and Command Pipeline.

---

## Decision

Adopt the **Snapshot Facade & Log** design with **mode‑as‑data (PromptSet)** and optionally a **light Engine + Store** for backends.

### Summary of the chosen approach

* **Immutable snapshots**: `ConversationState` + `Exchange` model the conversation; each `.ask()` returns a *new* snapshot.
* **Pure compile‑then‑execute**: construct `InitialCommand` from the snapshot, delegate to `GeminiExecutor.execute`, and build the next snapshot. No side effects.
* **Structured options**: policy/state produce `ExecutionOptions` (estimation/result/cache) without SDK coupling.
* **Source flexibility**: persistent edits via `with_sources`.
* **Batch**: `run(PromptSet.vectorized|sequential)` with normalized per‑prompt and aggregate metrics.
* **Observability**: audit fields on `Exchange`; `BatchMetrics`/`FlowMetrics` returned from API calls; optional event log in Store for durable audits.
* **Backends**: `ConversationEngine` + `ConversationStore` (JSON/SQLite/S3) with optimistic concurrency and copy‑on‑write persistence.

---

## Architectural alignment

* **Command Pipeline**: The extension only creates `InitialCommand` (with `history=(Turn, ...)`) and calls `GeminiExecutor.execute`. Planning, rate limits, adapters, and `ResultBuilder` remain untouched.
* **Essential Rubric**:

  * *Simplicity & Elegance* — tiny API (`ask`, `ask_many`, `ask_batch`, `run(Flow)`).
  * *Data over Control* — state is data; behavior is pure transforms; no hidden globals.
  * *Clarity & Explicitness* — persistence is opt‑in via Store adapters; metrics flow through core channels.
  * *Robustness* — immutability eliminates in‑place mutation; OCC in Store prevents lost updates.
  * *Extensibility* — cache and source deltas are explicit and provider‑agnostic seams.

---

## Options considered

1. **Snapshot Facade + Log + PromptSet (Chosen)**
   *Pros*: best DX, pure functions, audit‑grade, preserves core invariants, easy caching & source deltas.
   *Cons*: needs pruning policy for long histories; introduces minimal event/log concepts.

2. **Declarative Dialogue Plans only (Statecharts/DSL)**
   *Pros*: explicit flows; great for productized pipelines.
   *Cons*: over‑structured for ad‑hoc chat; more concepts to learn.

3. **Append‑only Store Engine only**
   *Pros*: concurrency & durability first.
   *Cons*: heavier ceremony for simple scripts; weak interactive ergonomics.

4. **Stateless Binder (formatting helpers)**
   *Pros*: lowest complexity; zero chance to violate core invariants.
   *Cons*: poor UX — users still manage loops & state; misses goals.

5. **Keep legacy `ConversationManager`** (rejected)
   *Pros*: no change for current users.
   *Cons*: mutable internals, limited cache/source flexibility, weaker observability; conflicts with immutability/determinism goals.
   *Decision*: Rejected in favor of the Snapshot Facade approach to maintain architectural purity and avoid compatibility debt.

---

## Consequences

### Positive

* **Trivial UX** for multi‑turn; scalable from notebooks to backends.
* **Deterministic** snapshots enable exact reproduction and golden tests.
* **Provider‑agnostic caching** via `CacheBinding` with future adapters in mind.
* **First‑class source editing** with delta‑based cache retention.
* **Batch metrics** readily available to user code without custom plumbing.
* **Clear seams** for persistence without contaminating the core.

### Negative / Risks

* **History size** can grow; mitigation: pruning policy knob and optional summarization before the next `InitialCommand`.
* **Adapter heterogeneity** for caching/metrics; mitigation: treat cache & metrics keys as optional and guard in code/tests.
* **Two user paths** (Facade vs Engine) could confuse; mitigation: documentation “When to use which API” and examples.

---

## Decision details

### Public API (high level)

* `Conversation.start(executor, sources=...) -> Conversation`
* `Conversation.ask(prompt: str) -> Conversation`
* `Conversation.run(prompt_set: PromptSet) -> (Conversation, tuple[str, ...], BatchMetrics)`
* Source editing: `with_sources(...)`
* Policy: `with_policy(ConversationPolicy(...))`

### Store contract (optional)

* `ConversationStore.load(conversation_id) -> ConversationState`
* `ConversationStore.append(conversation_id, expected_version, exchange) -> ConversationState`
* JSON/SQLite/S3 reference adapters use copy‑on‑write + atomic rename/WAL; optimistic concurrency on `version`.

---

## Migration / Rollout

* This is a **full rebuild** of the extension; no shim to legacy interfaces.
* Documentation highlights the extension’s **non‑core** status while modeling best practices.
* Contracts focus on immutability, determinism, OCC, metrics presence/absence, and cache/source delta semantics.

---

## Open questions / Future work

* **History summarization policy**: provide a built‑in summarizer strategy or keep purely as a hook.
* **Richer tool steps in Flow**: remain minimal for now; consider `tool(name, args)` once stable.
* **Unified idempotency keys**: expose helper `idempotency_key(conv_id, prompt_hash)` for backends.

---

## References

* Core API reference (`GeminiExecutor`, `InitialCommand`, `Turn`).
* Architecture rubric & Command Pipeline principles (immutable command transitions; single SDK seam; metrics via `ResultBuilder`).
