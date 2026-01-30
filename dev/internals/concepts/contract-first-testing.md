# Contract-First Testing — Architectural Compliance Through Tests

> Status: Methodology adopted. Examples below are illustrative and may reference target components from the Command Pipeline spec.

## Purpose & Scope

**Contract-First Testing** uses type contracts and architectural invariants to drive test design. For Pollux—built on immutable data flow, typed transformations, and explicit error handling—this methodology prevents whole classes of bugs and continuously verifies that the implementation still matches the intended **architecture**.

**In scope**:

- Why contract-first (vs. example-only) testing
- The test model (layers, invariants, fitness functions)
- How it maps to Pollux components and folders
- Minimal, illustrative test patterns

**Not in scope**:

- Exhaustive unit test reference (see `tests/**`)
- Step-by-step “how to run tests” (see How-to → Testing)

---

## Why Contract-First?

Traditional tests ask “*does this input produce the right output?*”. Contract-first asks a prior question:
**“Does the code obey the architectural contracts that make bugs unlikely?”**

For this project, those contracts include:

- **Immutable, typed states** (Command variants)
- **Stateless, single-responsibility handlers** (`handle(cmd) -> Result`)
- **Unidirectional pipeline** (no cycles; no hidden global state)
- **Explicit errors** (`Success`/`Failure`), not control-flow exceptions
- **Purity at planning time** (no SDK calls outside `APIHandler`)

When these hold, many defects are **structurally impossible**.

---

## The Four Layers (test stack)

1) **Contract Compliance**
   Prove each component meets its **type/behavior contract**.
   Examples: handler signature shape, immutability, purity.

2) **Architectural Invariants**
   Prove the **system rules** remain true.
   Examples: no SDK in planner; pipeline stages don’t regress.

3) **Integration Behavior**
   Prove the pipeline exhibits **expected emergent behavior**.
   Examples: failure propagation, telemetry surfaces.

4) **Architectural Fitness**
   Continuously **score** the architecture on simplicity, clarity, robustness, etc.
   Examples: meta-tests for test complexity, mocking rates, drift budgets.

> This page explains the model and shows small patterns. The concrete tests live in `/tests/` (see “Folder mapping” below).

---

## Core Contracts & Invariants (project-specific)

### Handler contract

- **Signature:** `async def handle(self, command) -> Result[Next, Error]`
- **Purity:** No I/O unless the handler’s role is to perform I/O (e.g., `APIHandler`)
- **No mutation:** Inputs are not mutated; outputs are new immutable values
- **Determinism:** Same inputs → same outputs

### Command state contract

- **Variants:** `InitialCommand → ResolvedCommand → PlannedCommand → …`
- **No invalid states:** A handler cannot receive a state it shouldn’t handle
- **Monotonic enrichment:** Later states strictly add information; never remove required fields

### Planning vs. execution

- **Planner:** No provider SDK calls; can use estimation adapters only
- **API Handler:** The only place that contacts SDKs and records usage/validation

### Error & telemetry contract

- **Errors:** Represented as `Failure(error)`; not thrown for control-flow
- **Telemetry:** Present but optional; when enabled, emits stable event names

---

## Folder mapping (tests → architecture)

Use these directories consistently; prefer short, single-purpose tests.

```text
tests/
contracts/                 # Layer 1 + 2: contracts & invariants
test_handler_contracts.py
test_command_states.py
test_planner_purity.py
test_error_semantics.py
workflows/                 # Layer 3: integration behavior
test_execution.py
test_config.py
test_contracts.py
characterization/          # Golden files (stable external behavior)
...
performance/               # Perf baselines (optional)
unit/                      # Small units if/when needed

```

> **TODO:** If any file drifts from this map, add a short README in `tests/` explaining the exceptions.

---

## Patterns (where to find longer examples)

See Deep Dive → Contract-First Testing Patterns for extended examples of the concepts above.

> **Note:** Fitness tests are heuristics. Keep thresholds generous and revise when they become noisy.

---

## How this aligns with our rubric

| Rubric criterion    | What the tests enforce                                            |
| ------------------- | ----------------------------------------------------------------- |
| **Simplicity**      | Short tests, low mocking, single-responsibility handlers          |
| **Data-centricity** | Immutability; typed Command states; pure transforms               |
| **Clarity**         | Explicit deps in signatures; determinism; no hidden state         |
| **Robustness**      | Invalid states unrepresentable; errors are data, not control-flow |
| **DX/Testability**  | Easy setup; small seams; stable telemetry names                   |
| **Extensibility**   | Pluggable handlers/adapters validated via contract tests          |

---

## Telemetry & drift hooks (for token estimates)

Contract-first doesn’t stop at structure; it **also** guards run-time expectations:

- `token_estimation.estimate.*` must exist when planner runs (if telemetry enabled)
- `token_validation.*` must exist after API execution
- **Invariant:** Planner never writes actual usage; API Handler never estimates tokens

> **TODO:** Add a small “telemetry schema” JSON in `docs/` and a CI check that emitted names match schema.

---

## Anti-patterns (to detect early)

- Contract tests that mock the world (symptom of hidden coupling)
- Long `setUp`/fixture forests (symptom of multi-responsibility components)
- Throwing for control-flow where `Failure` should be returned
- Estimation that imports/uses provider SDKs
- Mutating inputs (especially Command variants)

---

## Suggested CI gates

- Run `contracts` first; fail fast if a core invariant breaks
- Only then run `workflows`, `characterization`, and `unit`
- Track an **architecture score** (see below) as a trend line, not a hard gate (at first)

```python
# tests/contracts/test_architecture_score.py
def test_architecture_score_trend():
    # Placeholder: wire to real functions as they mature
    scores = {
        "simplicity": 5,
        "data_centricity": 5,
        "clarity": 5,
        "robustness": 4,
        "testability": 5,
        "extensibility": 5,
    }
    assert sum(scores.values()) / len(scores) >= 4.5
```

> **TODO:** Replace constants with simple scoring funcs (e.g., count of mocks, avg test length, % handlers with single public method).

---

## Related documents

- [Architecture at a Glance](../architecture.md)
- [Concept — Command Pipeline](./command-pipeline.md)
- [Concept — Token Counting & Estimation](./token-counting.md)
- [Deep Dive — Command Pipeline Spec](../deep-dives/command-pipeline-spec.md)
- [How-to — Testing](../../how-to/testing.md)
