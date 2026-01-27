# Command Pipeline Architecture – Conceptual Overview

> Status: Target architecture. Some elements reference components introduced gradually; see Deep Dive and ADR-0001 for details.
>
> Audience: Contributors and advanced users.
> Scope: Explanation (what/why), not API reference or full how-to.

## Purpose & Scope

The Command Pipeline is the **core architectural pattern** of the Pollux library. It enables *developer-consumers* to execute batched Gemini API requests efficiently, with predictable costs, strong testability, and clear control over data flow.

This architecture replaces earlier monolithic `BatchProcessor` and `GeminiClient` designs with a **composable, asynchronous, unidirectional pipeline**.

**In scope**:

- Conceptual model of the pipeline and its parts
- Guiding principles and quality goals
- High-level flow of data
- Rationale for key design choices

**Not in scope**:

- API signatures, code snippets, or file paths (see *Deep Dive* for technical details)
- Step-by-step usage (see *How-To Guides*)
- API parameter reference (see *Reference*)

---

## Guiding Principles

The Command Pipeline is designed against the **Architecture Rubric** (`../architecture-rubric.md`):

- **Radical Simplicity** – Minimize conceptual overhead, even with advanced features.
- **Explicit over Implicit** – No hidden state or “magic”; data flow and control are obvious.
- **Data-Centricity** – Complex state modeled in rich, immutable data objects; behavior is simple and predictable.
- **Architectural Robustness** – Prevent invalid states from being representable.
- **Superior Developer Experience** – Decoupled, testable, and easily extended.

---

## Core Pattern

The library is organized as an **asynchronous processing pipeline**:

1. User constructs a **Command** – an immutable object describing the request.
2. The Command is passed into the **Gemini Executor**.
3. The Executor runs it through an ordered sequence of **Handlers**, each producing a richer, immutable state.
4. The final Handler produces a **Result**, which is returned to the user.

Data flows *one way* through the pipeline; each stage is stateless and isolated.

**Conceptual Flow:**

```text
Command → Source Resolution → Planning → API Execution → Result Building
```

---

## Conceptual Components

### Command

Immutable request descriptor containing:

- User-specified sources, prompts, configuration
- Fields for enriched state populated by later handlers

### Handlers

Stateless components for a single transformation:

- **Source Handler** – resolves raw inputs to structured sources
- **Execution Planner** – decides batching, caching, token budgeting, and prompt assembly
- **API Handler** – executes the plan via the Gemini API, handling rate limits and errors
- **Result Builder** – parses responses, validates schema, calculates metrics

### Executor

User-facing orchestrator:

- Accepts a Command
- Passes it through the configured Handlers
- Returns the final Result

---

## Rationale & Trade-offs

- **Pipeline vs. monolith** – Clear separation of concerns, easier testing, predictable flow.
- **Immutable Commands** – Prevents unexpected mutation; ensures state validity at each stage.
- **Centralized planning** – Token logic, caching, batching decisions in one place for transparency.
- **Async-first** – Enables efficient parallelism for network and I/O-heavy stages.

---

## Quality Attributes

- **Testability** – Handlers testable in isolation.
- **Extensibility** – New Handlers can be added without altering others.
- **Robustness** – Type-level enforcement of valid state transitions.
- **Transparency** – Clear structure and role separation.

---

## Relationship to Legacy Architecture

The previous design centered on `BatchProcessor` and `GeminiClient`, with `ContentProcessor` and `FileOperations` handling sources. Orchestration and policy were spread across classes, creating hidden sequencing and tight coupling.

**What it was:**

- `GeminiClient` managed prompt assembly, caching, rate limiting, retries, and API execution.
- `BatchProcessor` handled batch vs. individual flows, comparison runs, and result shaping.
- `ContentProcessor`/`FileOperations` resolved mixed sources and built API parts.

**Key limitations:**

- **Implicit coupling** – Cache and prompt logic entangled in hidden flags and side effects.
- **Mixed concerns & duplication** – Batch vs. individual flows reimplemented similar logic.
- **Synchronous I/O** – Blocking operations limited scale-out.
- **Extension friction** – Adding a decision step required edits across multiple classes.

**Pipeline mapping:**

- **Command** → replaces ad-hoc args/kwargs; immutably captures sources, prompts, and policies.
- **Source Handler** → subsumes `ContentProcessor` + `FileOperations` for extraction and normalization.
- **Execution Planner** → centralizes logic from `GeminiClient` and caching/token decisions.
- **API Handler** → isolates rate limiting, retries, execution.
- **Result Builder** → formalizes response parsing, schema validation, and metrics.

**Net effect:** Unidirectional, explicit data flow; async-first parallelism; higher testability and extensibility; same outcomes delivered by composable handlers instead of monolithic classes.

> See [Deep Dive – Command Pipeline Spec §10](../deep-dives/command-pipeline-spec.md#10-legacy-comparison) for a detailed mapping of legacy pain points to pipeline resolutions.

---

## Diagram

```mermaid
flowchart LR
    User[Developer App] --> Command
    Command --> SH[Source Handler]
    SH --> EP[Execution Planner]
    EP --> AH[API Handler]
    AH --> RB[Result Builder]
    RB --> Result
```

---

## Related Documents

- [Deep Dive – Command Pipeline Spec](../deep-dives/command-pipeline-spec.md)
- [ADR-0001 – Command Pipeline](../decisions/ADR-0001-command-pipeline.md)
- [Architecture Rubric](../architecture-rubric.md)
- [Concept – Token Counting & Estimation](./token-counting.md)
- [Glossary](../glossary.md)
