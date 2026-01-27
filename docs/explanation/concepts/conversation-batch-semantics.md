# Conversation Batch Turn Semantics

This note explains the two batch modes implemented by the Conversation extension — sequential and vectorized — including what they are, how they operate, the resulting history and metrics, and guidance on when to use each. It also closes with a brief proposal for a planner hint derived from `ConversationState.cache` and why that improves ergonomics without polluting core concerns.

---

## TL;DR

- Sequential (`vectorized=False`, default): executes prompts one-by-one, appends one `Exchange` per prompt. Maximizes clarity, auditability, and determinism; predictable answers and per-turn metrics; higher total latency and overhead.
- Vectorized (`vectorized=True`): executes all prompts in a single pipeline call, then appends a single synthetic `Exchange` labeled `[vectorized xN]`. Great for cost/latency when the core truly supports vectorized Q/A; trickier history and per-prompt metrics. In the current core, prompts are joined for the mock path, so most users will find sequential behavior more intuitive for now.

---

## Shared Surface

Both modes return: `(new_conversation, answers: tuple[str, ...], BatchMetrics)`.

- `answers`: aligned to the input prompt order.
- `BatchMetrics.per_prompt`: normalized per-prompt metrics when available (sequential path fills these; vectorized may contain `{}` per prompt until richer telemetry is available).
- `BatchMetrics.totals`: aggregate metrics derived from pipeline telemetry (e.g., durations, token usage when present).

---

## Mode A — Sequential (vectorized=False)

- What it does: calls the pipeline once per prompt (in order), reusing the same sources/history. Each prompt produces one `Exchange` and extends the immutable state.
- History: one turn per prompt — ideal for audit, replay, and exact post-hoc analysis.
- Answers: one answer per prompt; deterministic with temperature=0 and stable config.
- Metrics: per-turn metrics are natural; batch totals are computed by summing per-turn values.
- Pros:
  - Most intuitive for users (each question is a turn).
  - Clear drift tracking (estimate vs. actual) per exchange.
  - Easy pruning (e.g., `keep_last_n`) without ambiguity.
- Cons:
  - More pipeline invocations → higher latency/overhead for large batches.
  - Slightly higher rate-limit pressure.

When to prefer it:

- Interactive scripts, notebooks, tutorials.
- Strict audit logs and deterministic reproduction.
- When multi-prompt vectorization isn’t available or behaves unexpectedly.

---

## Mode B — Vectorized (vectorized=True)

- What it does: builds an explicit execution plan of N calls with shared context (history, system, shared sources) and reuses a single shared cache/upload set. The extension appends a single synthetic `Exchange` with `user="[vectorized xN]"` and `assistant` as a joined preview of answers for audit traceability.
- History: exactly one synthetic turn representing the batch (keeps long histories compact).
- Answers: one answer per prompt in the returned tuple. The core aggregates usage across N calls and surfaces per-prompt usage when available.
- Metrics: returns aggregate metrics and per-prompt metrics in telemetry (mock path synthesizes predictable usage; real adapters report provider usage).
- Pros:
  - Lower latency and cost via context reuse and amortized uploads.
  - Reduced rate-limit pressure; fewer shared-context preparations.
  - History compaction: one entry per batch.
- Cons:
  - Less intuitive history since multiple prompts are represented by a single synthetic turn.
  - Per-prompt drift analysis depends on telemetry depth from adapters.

When to prefer it:

- Server-side, cost/latency-sensitive workloads.
- When adapters support true multi-prompt inference with good telemetry.
- When long histories must remain compact.

---

## Why default to `vectorized=False` (for now)

- Intuition: Users expect “one prompt → one turn/answer.” Sequential mode preserves that mental model and auditability.
- Current core behavior: The planner’s mock/minimal path joins prompts into one input, which produces a single real answer and padded empties, leading to surprising results for newcomers.
- Determinism and drift: Per-turn drift metrics are clearer and more actionable when each prompt is a distinct turn.

This default can be revisited once the planner/adapters fully support multi-prompt vectorization with:

- Distinct answers per prompt (no joining fallback), and
- Per-prompt metrics and token usage.

---

## Practical guidance

- Prefer sequential for correctness and clarity; switch to vectorized when optimizing for cost/latency and you want to reuse shared context across many prompts.
- If you need compact histories with vectorized mode, a future `record_history=False` knob could avoid appending the synthetic batch turn.
- For very long conversations, use `keep_last_n` in policy to bound history; combine with vectorized batches for efficiency.

## Examples

Sequential batch (two prompts → two turns):

```python
from pollux import create_executor
from pollux.extensions.conversation import Conversation
from pollux.extensions.conversation_types import PromptSet

executor = create_executor()
conv = Conversation.start(executor)
conv, answers, metrics = await conv.run(PromptSet.sequential("A?", "B?"))
```

Vectorized batch (shared context cached once; answers align to prompts):

```python
from pollux import create_executor
from pollux.extensions.conversation import Conversation
from pollux.extensions.conversation_types import PromptSet

executor = create_executor()
conv = Conversation.start(executor)
conv, answers, metrics = await conv.run(PromptSet.vectorized("A?", "B?", "C?"))
```

---

## Planner hint concept: mapping from `ConversationState.cache`

Goal: Let the extension provide deterministic, conversation-scoped cache context to the core planning stage **without** entangling core logic with extension internals.

### The idea

Thread a small, neutral hint (e.g., a deterministic cache key and known artifacts) from the conversation state into planning:

```python
# conceptual shape (extension-provided)
cache_hints = {
  "key": "conv:1234...",               # stable per conversation
  "artifacts": ("prov_cache_a", ...),  # provider-agnostic ids
  "ttl_seconds": 7200,                  # optional
}
```

The planner can choose to:

- Set or override `ExplicitCachePlan.deterministic_key` using `cache_hints["key"]` for stable cache reuse.
- Prefer existing `artifacts` where adapters support reusing known cache entries (via registries).
- Respect `ttl_seconds` when generating explicit cache instructions.

### Why it helps

- Deterministic reuse: Attaches cache identity to the conversation, avoiding accidental cross-conversation leakage and making reuse explicit.
- Cost control: Reuses uploads or cached content across turns, lowering tokens and latency.
- Separation of concerns: The extension only proposes hints; the planner owns cache decisions and remains provider-agnostic.
- Future-proof: If an adapter doesn’t support explicit caching, hints are safely ignored.

### Minimal, extensible seams (non-invasive)

- “Extras” bag on `InitialCommand` (optional field): planner *may* read `initial.extras.get("conversation_cache")`.
- Executor-level `HintProvider` hook: a strategy object computes neutral hints from `InitialCommand` and threads them into planner decisions.
- Use current `ExplicitCachePlan.deterministic_key`: populate from hints when present — zero behavior change unless hints are provided.

All options preserve the single SDK seam and keep core code clean while giving extensions a way to deliver QoL improvements (stable cache reuse, fewer uploads) without hidden magic.

---

## Summary

- Sequential and vectorized modes serve different priorities: clarity/audit vs. cost/latency.
- Defaulting to sequential matches user intuition and current core behavior; vectorized remains available for experienced users and backend flows.
- A modest hint mechanism from `ConversationState.cache` to planner can enable deterministic cache reuse and cost savings while keeping the architecture clean and extension-friendly.

---

What hints buy us: Better efficiency and determinism for cache reuse (stable “conversation cache identity” carried into planning), not correctness. Without hints, reuse relies on existing core behavior (e.g., registries, deterministic planner keys) and may be less predictable or leave cost savings on the table.
