# Conversation Extension – Conceptual Overview

## What this is

The **Conversation Extension** is an *optional* library API that layers on top of the Pollux core. It demonstrates how to build powerful features **without modifying the core pipeline**. It provides a tiny, immutable API for multi‑turn interactions, audit‑grade observability, cache reuse, and batch workflows — all as a **good citizen** of the architecture.

> Positioning: This is an **extension**, not core. It consumes the core’s public types (`InitialCommand`, `Turn`, `GeminiExecutor`) and follows the Command Pipeline’s rules: **single SDK seam, immutable command states, data‑over‑control, metrics via `ResultBuilder`.**

---

## Why it exists

* **Radical simplicity for multi‑turn**: trivial `.ask()` chains, `.ask_many()` and `.run(Flow)` without user‑written loops.
* **Deterministic, immutable** conversations: every call returns a new snapshot; original objects stay unchanged.
* **Audit‑grade**: events and metrics are captured without leaking pipeline concerns into the extension.
* **Extensibility by example**: serves as a reference for how to build extensions that align with the rubric and pipeline.

---

## Mental model

At the center is an **immutable snapshot**:

```python
@dataclass(frozen=True)
class Exchange:
    user: str
    assistant: str
    error: bool
    estimate_min: int | None = None
    estimate_max: int | None = None
    actual_tokens: int | None = None
    in_range: bool | None = None

@dataclass(frozen=True)
class ConversationState:
    sources: tuple[Any, ...]
    turns: tuple[Exchange, ...]
    cache_key: str | None = None
    cache_artifacts: tuple[str, ...] = ()
    cache_ttl_seconds: int | None = None
    policy: ConversationPolicy | None = None
    version: int = 0
```

The user works with a **Facade** wrapping a `ConversationState`. Each call creates a *new* conversation object. No in‑place mutation.

```python
conv = Conversation.start(executor, sources=[book_a, book_b])
conv = await conv.ask("Summarize chapter 3.")
conv = await conv.ask("List main characters.")
print(conv.state.last.assistant)
```

Under the hood, the extension constructs `InitialCommand` from `state` and delegates to the **single** pipeline seam (`GeminiExecutor.execute`). Metrics flow back through `ResultBuilder` and are attached to the `Exchange` as optional audit fields.

---

## Key concepts

### 1) Structured planning hints (vendor‑neutral)

Policy and state produce structured `ExecutionOptions` (estimation/result/cache overrides). The extension does not call SDKs or apply heuristics; it composes pure data that the pipeline consumes. Optional cache identity is carried via `cache_key` and surfaced as cache options.

### 2) Flexible source editing (persistent vs. ephemeral)

* Persistent edits return a *new* conversation: `with_sources`, `add_sources`, `remove_sources`, `replace_source`.
* Ephemeral overrides apply to a single ask: `await conv.ask("Q", sources=[...])`.
* Cache friendliness: the extension computes a **source delta**; unchanged sources keep their artifacts, replaced ones drop just their artifacts.

### 3) Batch in two styles

Batch behavior is expressed via `PromptSet`:

* **Vectorized**: `PromptSet.vectorized("Q1", "Q2")` yields one synthetic exchange with combined answers.
* **Sequential**: `PromptSet.sequential("Q1", "Q2")` yields one exchange per prompt.
* Both return **normalized metrics** (per‑prompt and totals) derived from pipeline telemetry.

### 4) Mode‑as‑data, no DSL

The extension keeps behavior explicit through `PromptSet` and `ConversationPolicy`, avoiding a general DSL to reduce concept count and ambiguity.

### 5) Engine + Store (backends)

For server/back‑end use, the `ConversationEngine` works with a `ConversationStore` (e.g., JSON/SQLite/S3) to load → execute → append, with **optimistic concurrency**. Front‑end and scripts usually just use the Facade.

---

## Relationship to the core

* **Immutable command transitions**: the extension only ever creates `InitialCommand` with typed `history=(Turn, ...)` and lets the pipeline transform it.
* **Single SDK seam**: only `GeminiExecutor.execute` is called. The extension never imports provider adapters directly.
* **Observability**: all usage/cost metrics originate in the pipeline and are *attached* to `Exchange` or returned as `BatchMetrics`/`FlowMetrics`; the extension does not invent its own counters.

---

## Design highlights (rubric alignment)

* **Simplicity & Elegance**: `.ask`, `.run(PromptSet)` keep the common path to one or two lines.
* **Data over control**: snapshots are plain data; behavior is the pure `extend()` function.
* **Robustness**: no mutable state; optional Engine+Store adds OCC and copy‑on‑write persistence.
* **Extensibility**: clear insertion points (policy/options, sources, metrics pass‑through). New modalities are new `ExecutionMode` implementations.
* **Good citizen**: file I/O is isolated in Store adapters; telemetry flows via core channels.

---

## When to use which API

* **Facade (`Conversation`)**: interactive sessions, notebooks, scripts. You want simplicity and local cache reuse.
* **Flow DSL**: deterministic multi‑step runs, tests, CI demos.
* **Engine + Store**: server endpoints or multi‑writer systems that need optimistic concurrency and durable audit logs.

---

## Example cookbook

### Swap sources mid‑conversation

```python
conv = Conversation.start(executor, sources=[book_a, book_b])
conv = await conv.ask("Summarize book A.")
conv = conv.replace_source(lambda s: s == book_b, new_source=book_c)
conv = await conv.ask("Compare A vs C.")
```

### Batch variants

```python
# Vectorized batch (one turn, many answers)
conv, answers, metrics = await conv.run(PromptSet.vectorized("Q1", "Q2", "Q3"))

# Sequential (multiple turns)
conv, answers, metrics = await conv.run(PromptSet.sequential("Outline", "Polish"))
```

---

## Concurrency & scaling notes

* The Facade is naturally single‑writer (by object identity). Use **Engine + Store** to coordinate multiple writers via optimistic concurrency.
* Very long histories: provide a policy to keep last *N* turns or perform summarization upstream before constructing the next `InitialCommand`.

---

## FAQ

**Is this replacing the core pipeline?** No. It composes the pipeline and shows how to *extend* it.

**Do I have to use the Store?** No. Most users only need the Facade. Stores matter for backends and audit trails.

**What if my provider doesn’t support explicit caching?** The cache binding becomes a no‑op; you still benefit where adapters support it.

**Can I add new source types?** Yes. Treat them as opaque identifiers with a stable fingerprint; adapters decide how to upload/cache.

---

## Glossary

* **Snapshot**: the immutable `ConversationState` at a point in time.
* **Exchange**: a single question/answer pair with optional audit fields.
* **Cache Binding**: explicit, conversation‑scoped cache identity and artifacts.
* **Flow**: a minimal, declarative sequence of steps compiled into calls to `extend()`.
* **Store**: an adapter responsible for loading/append‑only persistence with OCC.
