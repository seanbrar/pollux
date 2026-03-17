# Pollux Roadmap

This roadmap is intentionally scope-constrained. Pollux is already past the
"ship the core at all costs" phase; the next phase is to make the core more
trustworthy, more legible, and harder to misuse.

- **Intent**: communicate priorities and scope boundaries, not promises.
- **Last updated**: 2026-03-16
- **Current status**: v1.5 is complete. Realtime and deferred APIs are both in
  scope and shipped.
- **Status tracking**: Issues and PRs are the source of truth for active work.

## Product Strategy

- **Policy**: Pollux is capability-transparent, not capability-equalizing.
- Pollux owns orchestration primitives, not full application workflows.
- Prefer stronger guarantees, clearer docs, and sharper errors over a broader
  public API.
- New surface area should earn its place by removing repeated downstream
  boilerplate without hiding meaningful provider differences.
- Upstream concerns stay upstream: model quality, pricing, provider-side
  latency, and feature availability belong to providers.
- Downstream concerns stay downstream: scheduling, job queues, human review,
  storage, business workflows, and long-running agent policy belong to
  applications using Pollux.

## Current Position

The core library now covers the main orchestration responsibilities it set out
to own:

- Stable entry points for realtime and deferred execution:
  `run()`, `run_many()`, `defer()`, `defer_many()`,
  `inspect_deferred()`, `collect_deferred()`, `cancel_deferred()`.
- Multimodal source handling across the supported provider matrix.
- Source patterns: fan-out, fan-in, and broadcast.
- Context reuse through explicit caching, implicit caching where exposed, and
  provider-managed prompt caching where available.
- Structured outputs, tool calling, and conversation continuity.

That means the roadmap should no longer be "more features by default." The bar
for new work is now: does it make the existing contract more reliable or more
usable without expanding Pollux into a framework?

## Important Future Work

### 1. Provider Contract Hardening

- Expand characterization and real API coverage for the highest-drift
  boundaries: multimodal inputs, deferred lifecycle normalization, tool-call
  continuations, reasoning metadata, and routed-provider variability.
- Make capability drift easier to detect so the public capability docs stay
  aligned with real provider behavior.
- Keep unsupported combinations fail-fast, with concrete hints instead of
  silent degradation.

### 2. Deferred Delivery Operational Polish

- Improve docs and cookbook coverage for the real deferred operating model:
  handle persistence, polling cadence, collection, cancellation, partial
  failure handling, and backfill-style workflows.
- Keep the lifecycle intentionally small: submit, inspect, collect, cancel.
  Prefer better guarantees and diagnostics over more deferred entry points.
- Consider narrowly scoped controls for provider-owned deferred artifacts only
  when they solve a real operational problem without turning Pollux into a
  background job manager.

### 3. API Simplification After v1.5

- Remove or deprecate migration shims once they have served their purpose
  (example: legacy `Options.delivery_mode` compatibility).
- Keep the boundary between realtime and deferred execution explicit and hard
  to misuse.
- Continue pruning ambiguous naming and low-value convenience layers.

### 4. Production Ergonomics for Core Patterns

- Add stronger cookbook coverage for common production shapes: resume on
  failure, structured extraction, tool loops, and provider switching where the
  switch is truly one line.
- Improve guidance for adopting Pollux correctly on the first try, especially
  around caching, deferred delivery, and provider capability differences.
- Favor examples and documentation that reduce downstream rework over new
  abstractions in `src/pollux/`.

### 5. Selective Expansion, Not Breadth for Breadth's Sake

- Add new provider support or new capability surface only when it clearly
  reinforces Pollux's core job: delivering prompts and sources, reusing
  context, normalizing provider lifecycle behavior, and extracting stable
  results.
- Hold a high bar for parity adapters that mask provider differences and add
  maintenance cost.
- Prefer additive, low-policy features over broad "one API for everything"
  designs.

## High-Bar / Not Planned

The following are intentionally outside Pollux's target shape unless a very
strong case emerges:

- Workflow schedulers, background workers, cron abstractions, or queue systems
- Vector stores, retrieval frameworks, or document indexing pipelines
- Agent runtimes, planning frameworks, or memory systems
- Automatic parity layers that hide fundamental provider limitations
- Provider-agnostic knobs for every provider-specific feature
- Cross-job recovery systems that own application-level orchestration

## References

- Provider contract: `docs/reference/provider-capabilities.md`
- Testing philosophy: `TESTING.md`
- Contributor guidance: `docs/contributing.md`
