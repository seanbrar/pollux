# Pollux Testing Guide

**Based on Minimal Tests, Maximum Trust v0.1.0**

A testing standard that prioritizes signal over coverage, architecture over assertion, and clarity over volume.

---

## About This Document

This guide adopts the Minimal Tests, Maximum Trust specification for Pollux. It is divided into two parts:

- **Part I: Testing Philosophy** — Core principles for deciding what to test
- **Part II: Testing Structure** — Recommended organization for test files (optional)

For extended rationale behind these principles, see the [Minimal Tests, Maximum Trust Manifesto](https://github.com/seanbrar/minimal-tests-maximum-trust/blob/main/MANIFESTO.md) (optional background reading).

---

## Table of Contents

- [About This Document](#about-this-document)
- [License](#license)
- [Part I: Testing Philosophy](#part-i-testing-philosophy)
  - [Purpose](#purpose)
  - [Principles](#principles)
  - [What This Is Not](#what-this-is-not)
  - [Test Categories](#test-categories)
  - [Evaluating Existing Tests](#evaluating-existing-tests)
  - [On Coverage Metrics](#on-coverage-metrics)
- [Part II: Testing Structure (Recommended)](#part-ii-testing-structure-recommended)
  - [Tenets](#tenets)
  - [Defining Boundaries](#defining-boundaries)
  - [Test Placement](#test-placement)
  - [Project Conventions (Optional)](#project-conventions-optional)
  - [Known Limitations](#known-limitations)
  - [Relationship Between Parts](#relationship-between-parts)
- [Adapting This Specification](#adapting-this-specification)
- [Changelog](#changelog)

---

## License

This specification is released under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Copy, adapt, and redistribute without restriction.

---

## Part I: Testing Philosophy

### Purpose

A test suite should produce meaningful information about system correctness. Tests that fail should indicate genuine problems. Tests that pass should inspire confidence. Tests that do neither are overhead.

These principles guide decisions about what to test, what to leave untested, and how to evaluate the usefulness of existing tests.

---

### Principles

#### 1. Signal over coverage

Coverage measures what tests *execute*, not what *requires* testing. A codebase at 95% coverage with hollow tests is in worse shape than one at 70% coverage with tests that catch real bugs.

Prioritize tests that catch real problems over tests that merely touch code.

#### 2. Trust the architecture

Well-designed systems prevent invalid states through structural means: type constraints, immutable data structures, factory methods with validation, and compile-time or static-analysis checks.

> Examples in this section use Python constructs. The underlying principles apply to any language with equivalent mechanisms—record types, sealed classes, builder patterns with validation, etc.

When the architecture prevents a class of errors, tests verifying that prevention add maintenance burden without adding safety. Examples:

| Architectural guarantee | Why testing is unnecessary |
|------------------------|---------------------------|
| Immutable data structures | Mutation is impossible by construction |
| Factory methods with validation | Invalid objects cannot be created |
| Type constraints (e.g., literals, enums) | Static analysis rejects invalid values |
| Post-initialization validation | Invalid inputs are rejected before objects exist |

Architectural protection means the constraint is visible: a type signature, a frozen decorator, a validation call. If a reviewer can verify the protection exists by looking at the code or running static analysis, the architecture is doing the testing. Tests should focus on behavior that the architecture does not already guarantee.

#### 3. Test at boundaries

The most valuable tests operate at system boundaries:

- Where external input enters the system
- Where output leaves the system
- Where subsystems integrate
- Where the system interacts with external dependencies

Interior logic—when deterministic, type-safe, and exercised through boundary tests—often does not require dedicated unit tests. Bugs in interior modules surface through boundary tests; dedicated interior tests may duplicate coverage without adding signal.

#### 4. Regression-driven growth

Tests written in response to actual bugs have demonstrated value. They encode specific failure modes that occurred in practice.

New code should have minimal smoke tests verifying basic functionality. Additional targeted tests should be added when bugs are discovered. Let the suite grow from experience, not speculation.

#### 5. Complexity indicates design feedback

When code requires extensive testing to achieve confidence, the code itself may be too complex. A high density of tests around a module can indicate:

- Too many code paths
- Implicit state that is difficult to reason about
- Unclear contracts between components

Before adding tests to manage complexity, consider whether the code could be simplified.

#### 6. Intentional gaps

Not all code requires dedicated tests. However, untested code should be intentional, not accidental.

**Valid reasons to omit tests:**

- The architecture prevents the failure mode
- The code is exercised transitively through boundary tests
- The code is trivial delegation with no logic
- The code is deterministic and tested through integration

**Invalid reasons to omit tests:**

- The code appears simple
- The author is confident it works
- Testing will be added later

When code is intentionally untested, the rationale should be articulable. If it cannot be explained structurally, the code should be tested.

---

### What This Is Not

This specification is not permission to:

- **Skip tests because the code seems simple.** Simplicity is not a structural argument.
- **Ignore coverage entirely.** Coverage is a useful signal—just not the goal.
- **Delete tests without justification.** Every removal should be explainable.
- **Avoid testing new code.** New code gets smoke tests; targeted tests follow bugs.

The goal is intentional testing, not absent testing.

---

### Test Categories

Tests serve different purposes. The following categories are ordered by typical value:

| Category | Purpose | When to write |
|----------|---------|---------------|
| **Boundary tests** | Verify behavior at system entry and exit points | Always, for each significant boundary |
| **Regression tests** | Prevent recurrence of specific bugs | After every bug caught late or reaching production |
| **Contract tests** | Verify architectural invariants spanning modules | When invariants affect correctness and cannot be verified by inspection |
| **Characterization tests** | Capture output format when stability matters | When output is consumed externally or drift is hard to detect |
| **Unit tests** | Verify isolated complex logic | When boundary tests do not adequately cover edge cases |

Integration and boundary tests form the backbone of a well-designed suite. Unit tests are appropriate for genuinely complex logic but should be the exception, not the rule.

---

### Evaluating Existing Tests

When reviewing a test suite, ask of each test:

1. **Does it provide signal?** If it failed, would you investigate the code or adjust the assertion?
2. **Does it duplicate coverage?** Is the same behavior verified elsewhere?
3. **Does it verify a language guarantee?** The runtime already enforces immutability, enum semantics, and similar constraints.
4. **Does it encode implementation rather than behavior?** Would a refactor that preserves behavior break this test?

Tests answering "no" to the first question, or "yes" to the others, are candidates for removal or consolidation.

---

### On Coverage Metrics

Coverage is a diagnostic tool, not a goal.

When reporting or evaluating coverage:

- Distinguish between code that *should* be tested and code that is *protected by architecture*
- Use coverage exclusions with explanations for intentional gaps
- Communicate coverage in context—explain why, not just what

High coverage with low-signal tests provides false confidence. Moderate coverage with high-signal tests provides genuine protection.

---

## Part II: Testing Structure (Recommended)

This section describes an organizational approach called **Boundary-First Flat Structure**. It complements the testing philosophy but is not required. Projects with different organizational needs may adopt Part I without Part II.

---

### Tenets

#### 1. One file per boundary

A boundary is where user input enters, output leaves, or subsystems integrate. Each boundary gets one test file—not one per source module, not one per test category.

#### 2. Flat over nested

No directory hierarchy mirroring source structure. To find tests for a module, search by boundary responsibility, not by path.

#### 3. Markers over directories

Test *type* (unit, integration, contract, api) is expressed via test framework markers, not directory placement. Select tests by marker regardless of which file contains them.

#### 4. Interior modules do not need dedicated tests

Handlers, adapters, and internal logic are tested through their boundary. A bug in an interior module surfaces in the boundary test that exercises it.

---

### Defining Boundaries

Boundaries are specific to each project. Pollux adopts the following boundaries.

<!-- BEGIN CUSTOMIZATION: Replace this table with your project's boundaries -->

| Boundary | Responsibility |
|----------|----------------|
| Configuration and CLI | Config resolution (env/project/home/overrides), validation, and redaction; `pollux-config` outputs |
| Public Python API | `run_simple`, `run_batch`, `create_executor`, and frontdoor input normalization |
| Pipeline execution | End-to-end command pipeline from `InitialCommand` to `ResultEnvelope`, including caching/upload stages |
| External provider integration | Gemini adapter calls, file uploads, cache creation, token counting, and real API IO |
| Extensions and persistence | Conversation store/engine, research helpers, and provider upload utilities |

<!-- END CUSTOMIZATION -->

New boundaries should be rare. If you're creating a new test file, first ask whether the test belongs to an existing boundary.

---

### Test Placement

For any new test, determine placement by boundary responsibility.

<!-- BEGIN CUSTOMIZATION: Replace with your project's test placement guide -->

```
Is this an architectural invariant that spans modules?
  → Contract tests (tests/test_contracts.py)

Does this test configuration or CLI behavior?
  → tests/test_config.py

Does this test public API entry points or frontdoor input handling?
  → tests/test_frontdoor.py (or the closest boundary file)

Does this test pipeline execution or end-to-end flows?
  → tests/test_pipeline.py

Does this test extensions or persistence boundaries?
  → tests/test_extensions.py (or the closest boundary file)

Does this require a real external service?
  → A dedicated test file marked `api` and gated by ENABLE_API_TESTS

None of the above?
  → Probably belongs in an existing boundary file.
     If genuinely new, justify the new boundary.
```

<!-- END CUSTOMIZATION -->

---

### Project Conventions (Optional)

<!-- BEGIN CUSTOMIZATION: Add your project's conventions -->

- Boundary tests live in `tests/test_{boundary}.py` and stay flat at the repo root.
- Use module-level markers (`pytestmark`) to declare the primary test type.
- Characterization (golden) tests live under `tests/characterization/` and are always marked `characterization`.
- External-service tests must be marked `api` and require an explicit enable flag plus API credentials.
- Shared fixtures and helpers remain centralized in `tests/conftest.py` and `tests/helpers.py`.

<!-- END CUSTOMIZATION -->

---

### Known Limitations

**Scale**: The flat structure is designed for small-to-medium projects with well-defined boundaries. Large projects with many boundaries may find that one file per boundary becomes unwieldy. Part II is optional for this reason—such projects may adopt Part I while organizing tests differently.

---

### Relationship Between Parts

Part I (Philosophy) answers: *Should I write this test?*

Part II (Structure) answers: *Where does it go?*

The philosophy provides principles applicable to any project. The structure applies those principles through a specific organizational approach suited to projects with well-defined boundaries.

---

## Adapting This Specification

The Minimal Tests, Maximum Trust specification is designed to be adopted by projects and adapted to their specific boundaries. The following guidelines define MTMT compliance.

### Compliance Requirements

**Part I (Testing Philosophy)** — Preserve unchanged. These principles define what it means to follow this standard. The sections from "Purpose" through "On Coverage Metrics" are normative.

**Part II (Testing Structure)** — If adopting Part II:
- **Tenets**: Preserve unchanged. These define the Boundary-First Flat Structure approach.
- **Defining Boundaries**: Replace the example table with your project's actual boundaries.
- **Test Placement**: Replace the example decision tree with one tailored to your boundaries.
- **Project Conventions**: Add your project-specific guidance here (optional).
- **Known Limitations** and **Relationship Between Parts**: Preserve unchanged.
- **Customization markers**: The `<!-- BEGIN/END CUSTOMIZATION -->` comments may be preserved to document which sections contain project-specific content. This aids future upgrades and clarifies provenance.

If Part II does not fit your project, you may omit it entirely while remaining Part I compliant.

### Instructional Text

Sentences guiding the adoption process (e.g., "replace the table below," "adapt to your system's boundaries") are scaffolding. Remove or adapt them in your project's version. Only the substantive content of each section must be preserved—not the instructions for how to customize it.

### Version Reference

Preserve the version number (`v0.1.0`) in your adopted document. This indicates which iteration of the standard your project follows.

If you customize the document title, include the version reference in the header:

> # [Project Name] Testing Guide
> **Based on Minimal Tests, Maximum Trust v0.1.0**

When the specification is updated, you may choose to update your adoption or remain on the previous version.

---

## Changelog

### v0.1.0

- Initial specification
