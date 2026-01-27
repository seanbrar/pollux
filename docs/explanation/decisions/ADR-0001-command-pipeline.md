# ADR-0001: Adopt Asynchronous Handler Pipeline for Pollux Execution

**Date:** 2025-08-11
**Status:** Accepted
**Tags:** architecture, pipeline, execution, planning, handler-pattern
**Audience:** Contributors and extension authors
**Impacted Modules/APIs:** `executor.GeminiExecutor`, pipeline handlers (`source_handler`, `planner`, `api_handler`, `result_builder`), typed Command states

---

## Context

The original Pollux design centered on `BatchProcessor` and `GeminiClient`. These classes handled:

- Prompt assembly
- Source resolution
- Caching decisions
- Token counting
- Rate limiting and retries
- API execution
- Result shaping

This design worked but had limitations:

- **Hidden sequencing** – execution order encoded in method calls and internal state
- **Mixed responsibilities** – planning and execution logic interleaved
- **Synchronous bottlenecks** – blocking I/O limited throughput
- **Extension friction** – adding new decision steps required changes across multiple classes
- **Scattered telemetry/error handling** – cross-cutting concerns mixed with core logic

---

## Decision

Adopt an **asynchronous, unidirectional Command Pipeline** built from stateless Handlers that transform immutable Command objects through discrete stages.

### Key Elements

- **Immutable Commands** – Rich, typed objects representing the request at each stage
- **Handlers** – Stateless, single-responsibility components:
  - Source Handler
  - Execution Planner
  - API Handler
  - Result Builder
- **Executor** – Configures and runs handlers in sequence
- **Async-first** – Handlers and executor are async-native for concurrency

### Enhancements

- Typed Command states to prevent invalid transitions
- Configurable pipelines for extension without core modification
- Explicit fallback plans in `ExecutionPlan`
- Unified `Result` type (`Success` / `Failure`) for error handling

---

## Consequences

**Positive**:

- Clear separation of concerns
- State validity enforced by types
- Easier testing (handlers testable in isolation)
- Async concurrency improves throughput
- Extension points well-defined

**Negative**:

- Requires more up-front architectural discipline
- Additional data classes compared to monolithic approach
- May require adaptation effort for contributors familiar with legacy flow

---

## Alternatives Considered

- **Refactor existing classes** – Would reduce some coupling but preserve hidden sequencing
- **Keep monolithic client and introduce sub-modules** – Improves organization but not flow predictability or testability
- **Event-driven architecture** – More flexibility but higher complexity and less predictable flow for batch execution

---

## References

- [Concept – Command Pipeline](../concepts/command-pipeline.md)
- [Deep Dive – Command Pipeline Spec](../deep-dives/command-pipeline-spec.md)
- [Architecture Rubric](../architecture-rubric.md)

---

## Follow-up work (migration outline)

- Introduce `pipeline/` package: `base.py`, `source_handler.py`, `planner.py`, `api_handler.py`, `result_builder.py`.
- Add `GeminiExecutor` entry point and typed command variants.
- Migrate token logic into planner; use adapter-based estimation (see ADR-0002).
- Add unified `Result` type and explicit fallback in `ExecutionPlan`.
- Wire telemetry per handler; keep SDK calls in `APIHandler` only.
