# ADR-0009: Prompting System

**Status:** Accepted
**Date:** 2025-08-23
**Scope:** `src/pollux/pipeline/prompts/*`, planner integration, configuration keys under `[prompts]`
**Audience:** Contributors and extension authors
**Impacted Modules/APIs:** Planner prompt assembly, `PromptBundle`, prompt config keys, adapter `api_config` system instruction pass-through

---

## Context

The legacy planner constructed prompts by directly joining `initial.prompts` into a single `TextPart`. There was **no first‑class system instruction**, no clean way to append source‑aware guidance, and no supported path for **file‑based** or **advanced** prompt customization. This caused:

* Hard‑coded logic in planner, mixing composition with planning concerns.
* Weak extensibility (users edited planner code to change prompts).
* Cache keys that could not account for system‑level instructions.
* Minimal observability for prompt provenance.

At the same time, we needed to preserve strict batching semantics: **the number of user prompts determines expected outputs**.

---

## Decision

Adopt **PromptBundle + Assembler** as the dedicated prompt composition mechanism inside the Execution Planner, with:

* A tiny immutable **PromptBundle** (`user`, `system`, `hints`).
* A pure **default assembler** driven by configuration (prefix/suffix, optional system, optional source‑aware block).
* **File support**: `system_file`, `user_file` with guarded reading and clear precedence.
* An optional **builder hook** (`prompts.builder`) for advanced users to fully control assembly while respecting invariants.
* **Cache determinism**: include `system` in the explicit deterministic cache key when present.
* **Telemetry**: provenance and size metrics emitted at assembly time.

The assembler remains **within the Execution Planner**, preserving the Command Pipeline’s component boundaries and the single SDK seam.

---

## Consequences

### Positive

* **Radical Simplicity**: one data object, one pure function.
* **Extensibility**: configuration and file inputs cover 95% of use cases; hook covers the rest.
* **Safety**: batching invariants preserved; file reads capped and validated.
* **Determinism**: cache keys reflect the full effective prompt (system + user).
* **Observability**: prompt provenance and lengths captured for audits.

### Negative / Risks

* Providers without native system instruction will **ignore** `system`; behavior gracefully degrades.
* The builder hook may be abused for complex logic; guidance and tests mitigate this.
* Additional config keys under `[prompts]` slightly expand surface area.

---

## Options Considered

1. **PromptBundle + Assembler (Chosen)**

   * *Pros*: smallest surface, easy to test, aligns with pipeline; minimal planner changes.
   * *Cons*: introduces a small new module; relies on adapters to honor `system`.

2. **PolicyMap (TOML‑driven recipes only)**

   * *Pros*: zero code for users; highly declarative.
   * *Cons*: not flexible enough for edge cases; still needs a data carrier.

3. **External Hook only**

   * *Pros*: maximum flexibility; core stays tiny.
   * *Cons*: discoverability, uneven quality; encourages per‑team divergence.

4. **Block DSL**

   * *Pros*: powerful declarative composition.
   * *Cons*: overkill for scope; violates “radical simplicity”.

---

## Detailed Design Notes

* **Data model**: `PromptBundle(user: tuple[str, ...], system: str | None, hints: Mapping[str, Any])`.
* **Assembler**: pure function over `ResolvedCommand` + frozen config snapshot; no network I/O; local file reads only when configured.
* **Precedence**: inline `system` > `system_file`; existing `initial.prompts` > `user_file`.
* **Source awareness**: `apply_if_sources` appends `sources_block` to **system**.
* **Cache key**: planner’s deterministic key includes system text when present.
* **Adapter seam**: `system` passed via neutral `api_config["system_instruction"]` until a first‑class field is standardized across adapters.

---

## Migration Plan

1. **Introduce types & default assembler** behind a feature‑flag or guarded import; default behavior unchanged when no `[prompts]` keys are set.
2. **Planner integration**: assemble bundle, join `bundle.user` as before; carry `bundle.system` in `api_config`.
3. **Config wiring**: document keys under `[prompts]`; add validation and byte‑size limits for files.
4. **Telemetry**: emit `user_from`, `system_from`, lengths, and file paths.
5. **Tests**: unit tests for precedence and file behavior; integration tests for count invariants and cache‑key differences.

Rollback: revert to the legacy join if issues are found; because user prompts are preserved, rollback is safe.

---

## Test Plan (high level)

* **Unit**: assembler precedence; file errors (missing/too large/encoding); `apply_if_sources` logic.
* **Property**: `len(bundle.user) == len(initial.prompts) or (initial.prompts==() and bundle.user==(x,))`.
* **Integration**: planner uses bundle; expected count equals user length; cache key differs when system differs.
* **Adapter smoke**: providers accept/ignore `system_instruction` without failure.

---

## Open Questions / Future Work

* Promote `system_instruction` to a typed field on `APICall` once adapter coverage is universal.
* Consider optional **templating tokens** (e.g., `{source_count}`) if demand arises, keeping assembler pure and data‑only.
* Explore **org‑level prompt policies** layered below project config.

---

## Decision Rationale

This approach **maximizes clarity** and **minimizes footprint** while meeting all goals: removing hard‑coded planner prompts, enabling configuration and file inputs, preserving batching semantics, and maintaining a single SDK seam. It fits the architectural rubric (Radical Simplicity, Data‑centricity, Explicit over Implicit) and leaves room for advanced usage via a single, testable hook.
