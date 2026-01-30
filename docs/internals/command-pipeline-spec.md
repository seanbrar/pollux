# Command Pipeline – Technical Specification

> Status: Target state. Where names differ from current code on this branch, treat this as the authoritative spec (see ADR-0001).

## 1. Overview

This document details the technical architecture, data structures, and component responsibilities for the Command Pipeline. It assumes familiarity with the Pollux codebase.

---

## 2. Architectural Pattern

The pipeline is an `async`-native, ordered list of `BaseHandler` instances. Each Handler:

- Implements `async def handle(self, command) -> command`
- Receives an immutable Command variant (typed per stage)
- Returns a new immutable Command variant for the next stage

---

## 3. Core Data Types

### Command Variants

```python
@dataclass(frozen=True)
class InitialCommand: ...
@dataclass(frozen=True)
class ResolvedCommand: ...
@dataclass(frozen=True)
class PlannedCommand: ...
```

- Prevents invalid stage transitions
- Eliminates “optional hell” by ensuring required fields exist at each stage

### Source

Structured metadata for resolved inputs:

- Type, identifier, mime type, size, lazy content loader

### ExecutionPlan

Explicit instructions for API execution:

- Model, parts, API config
- Cache usage strategy
- Optional fallback plan

> **Legacy note:** These responsibilities were combined inside `GeminiClient`, which:
>
> - Assembled prompts and parts (`PromptBuilder`, `ContentProcessor`)
> - Chose cache strategy (`CacheManager.plan_generation`, `TokenCounter`)
> - Built API configs and applied overrides (`types.GenerateContentConfig`)
> - Enforced rate limits and retries (`RateLimiter.request_context`)
> - Executed requests and post-processed responses
>   Centralizing in one class obscured planning vs. execution. The pipeline splits these into `Execution Planner` and `API Handler`.

---

## 4. Pipeline Components

### Source Handler

- Resolves raw sources into `Source` objects
- Decouples identification from content processing

### Execution Planner

- Performs token estimation
- Selects caching strategy
- Decides payload construction (inline vs. file upload)
- Assembles prompt

### Rate Limit Handler

- Enforces `RateConstraint` prior to API execution
- Emits structured telemetry for wait times

### API Handler

- Executes `ExecutionPlan` via provider SDKs
- Handles uploads and caching when supported
- Retries (limited) and single fallback execution
- Wraps API errors with context

### Result Builder

- Parses output
- Validates schema
- Calculates efficiency metrics
- Merges telemetry

---

## 5. Executor

```python
class GeminiExecutor:
    def __init__(self, config: GeminiConfig, extra_handlers=None): ...
    async def execute(self, command: Command) -> dict: ...
```

- Configures and runs the Handler sequence
- Supports injection of extra Handlers

---

## 6. Integrated Addenda

- **Typed Command states** – Guarantee valid stage order
- **Configurable pipelines** – User may inject/replace Handlers
- **Fallback in ExecutionPlan** – Explicit primary/fallback calls
- **Unified Result type** – `Success` / `Failure` variants replace ad-hoc exceptions

---

## 7. Directory Structure

Matches updated pipeline roles under `/src/pollux/pipeline/`.

---

## 8. Error Handling

- Fail fast with `Failure` result variant
- Avoid silent retries unless explicit in plan

---

## 9. Observability

- Telemetry context wraps execution
- Handlers emit structured telemetry events

---

## 10. Legacy Comparison

**Mixed planning and execution**:

- `BatchProcessor._process_batch` combined prompt assembly, API orchestration, metrics, and result shaping.
- `GeminiClient._execute_generation` mixed prompt mutation, part construction, cache planning, and execution.
  → **Pipeline** separates into `Execution Planner` (decisions) and `API Handler` (execution).

**Implicit coupling and hidden state**:

- `GeminiClient` mutated `content` mid-flow; cache behavior depended on internal flags and `CacheManager`.
- Source extraction spanned multiple classes with side effects in orchestration.
  → **Pipeline** uses immutable Commands and dedicated Source Handler; side effects are localized.

**Synchronous I/O and serial flows**:

- Blocking sleeps in `RateLimiter`; sequential per-question calls; blocking downloads/uploads.
  → **Pipeline** uses async handlers for parallel source resolution, uploads, and batched execution.

**Extension and testing friction**:

- Adding token budgeting or new cache heuristics required edits across core classes.
  → **Pipeline** enables adding Handlers without modifying existing ones.

**Cross-cutting error/telemetry concerns**:

- Error handling and telemetry interleaved with business logic.
  → **Pipeline** moves errors into `Failure` results and telemetry into per-handler context.

---

## 11. Related Docs

- [Concept — Command Pipeline](../concepts/command-pipeline.md)
- [ADR-0001 — Command Pipeline](../decisions/ADR-0001-command-pipeline.md)
- [Concept — Token Counting & Estimation](../concepts/token-counting.md)
- [ADR-0002 — Token Counting Model](../decisions/ADR-0002-token-counting-model.md)
