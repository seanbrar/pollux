# Configuration System — Conceptual Overview

> Audience: Engineers designing, extending, or reviewing `pollux`’s configuration.
> Scope: Concepts, rationale, trade‑offs, and relationships to the Command Pipeline.

---

## Executive Summary

The configuration system resolves settings from **multiple sources** into a single, immutable `FrozenConfig` that flows through the **Command Pipeline**. It implements the **Pydantic Two-File Core** pattern with **resolve-once, freeze-then-flow** semantics, providing **predictable precedence**, **audit‑grade origin tracking**, and **extensible provider inference**.

* Resolve once, use everywhere. Inputs (programmatic/env/files/defaults) are merged before pipeline entry using Pydantic; the result is frozen and attached to the initial command.
* Precedence: `Programmatic > Environment > Project pyproject.toml > Home config > Defaults` with optional `POLLUX_PROFILE` selection.
* Auditability: A SourceMap records where each effective value came from, with comprehensive secret redaction.
* Extensibility: Pattern-based provider inference via `resolve_provider`; extra fields validation with pattern-based warnings; environment-gated debug audit via Python warnings.
* Testing & overrides: `config_scope()` provides entry‑time scoped overrides (async‑safe); the pipeline itself only sees the frozen snapshot.

This design replaces the previous primarily env/scope‑driven approach with a **typed, validated** backbone and **first‑class file‑based profiles**, improving clarity, extensibility, and auditability.

---

## Design Goals & Non‑Goals

### Goals

* **Data over control:** Model configuration as **data**, not behavior; keep logic at the edges.
* **Immutability:** The pipeline consumes a `FrozenConfig`; handlers/readers never mutate configuration.
* **Predictable precedence:** Documented and testable merge order; **no action‑at‑a‑distance** during execution.
* **Multi‑init ergonomics:** Support programmatic args, environment variables, and `pyproject.toml`/home profiles.
* **Audit‑grade observability:** Explain *why* a value is what it is, without leaking secrets.
* **Provider neutrality with clear seams:** Gemini is first‑class, but adding a provider should not disturb core.

### Non‑Goals

* Hot/live reload of config during a run.
* Secrets manager integrations (may be added at the file‑loader seam later).
* Cross‑process global state or global mutation.

---

## Mental Model

Think of configuration as **layers** that are merged **once** into a single, immutable object:

```text
Programmatic overrides
        ⬇
Environment (POLLUX_*)
        ⬇
Project pyproject.toml  [tool.pollux] / [tool.pollux.profiles.*]
        ⬇
Home   ~/.config/pollux.toml  (optional)
        ⬇
Defaults (schema)
        ⬇  merge
   Resolved settings + SourceMap (origins per field)
        ⬇  freeze
              FrozenConfig  → attached to Initial Command → pipeline
```

**Only the frozen snapshot enters the pipeline.** No further resolution occurs while handlers run.

---

## Core Concepts

### 1) Settings schema (validation)

* Implemented with **Pydantic BaseModel** providing strong typing, field validation, and automatic coercion.
* Captures **defaults** with Field descriptors and env integration (`POLLUX_` prefix); `.env` support via python-dotenv (opt-in).
* Uses **extra='allow'** to preserve unknown fields for extensibility while validating known fields.
* Cross-field validation (e.g., `api_key` required when `use_real_api=True`) with clear error messages.

### 2) SourceMap (auditability)

* For each field, record **origin**: `default | home | project | env | overrides`.
* Expose a redacted audit view (e.g., `api_key → env:GEMINI_API_KEY`).
* Feed metrics (counts per origin) to observability without leaking values.

### 3) FrozenConfig (immutability)

* A **frozen dataclass** representing the effective configuration.
* Attached to `InitialCommand` and passed along unchanged.
* Makes **invalid states unrepresentable** (types & invariants at construction time).

### 4) Provider inference

* Pattern-based mapping implemented by `resolve_provider(model: str) -> str`.
* Compiled patterns support exact names, version patterns, and simple prefixes.
* Defaults: Google (`gemini-*`), OpenAI (`gpt-*`), Anthropic (`claude-*`); fallback to Google.

### 5) Extra fields validation

* **Pattern-based validation** for unknown fields using regex patterns and type hints.
* **Non-breaking warnings** for deprecated patterns (e.g., `legacy_*`) and type mismatches.
* **Conventional patterns:** `*_timeout` (int), `*_url` (str), `experimental_*` (any), `legacy_*` (deprecated).
* **Graceful degradation** - warnings never break configuration resolution.

### 6) Debug audit emission

* Controlled by `POLLUX_DEBUG_CONFIG`.
* Emitted via Python’s `warnings` module (redacted audit); by default warnings print once per callsite.
* Stateless implementation keeps resolution thread-safe.

### 7) Scoped overrides (entry‑time only)

* `config_scope()` (ContextVar) allows **temporary overrides** for a block/task/test.
* On pipeline entry we **resolve and freeze**; handlers never observe ambient layers.

---

## Precedence & Profiles

* **Order:** `Programmatic > Env > Project pyproject.toml > Home file > Defaults`.
* **Profiles:** In files, configuration lives under:

  * Project: `pyproject.toml` → `[tool.pollux]` or `[tool.pollux.profiles.<name>]`
  * Home: `~/.config/pollux.toml` with the same tables
* **Selection:** `POLLUX_PROFILE=<name>` chooses a profile; if absent, the root table is used.
* **Conflict rule:** Higher layer always wins **per field**; unprovided fields fall back to lower layers.

**Rationale:** Teams get project‑level defaults; individuals can keep home profiles; CI and scripts can override via env; code can override anything programmatically.

---

## Lifecycle

1. **Call site** (executor/CLI/tests) assembles optional **programmatic overrides** and an optional `profile`.
2. **Resolver** loads: env → project file → home file → defaults, applies **profile**, and merges **programmatic last**.
3. **SourceMap** is created; **secrets are redacted** in any human‑readable view.
4. **Validation** runs once; any errors are precise and early.
5. **Freeze** into `FrozenConfig` and attach to `InitialCommand`.
6. Pipeline runs with **pure data**; adapters may request a provider view via the registry.

---

## Why This Design

### Alignment to the Command Pipeline

* **Immutable Commands:** `FrozenConfig` is part of the command payload; handlers consume, never mutate.
* **Single SDK seam:** Provider adaptation occurs at one seam, not scattered through handlers.
* **Data‑centric:** Decisions (caching, tiers, model selection) are driven by **data fields** with explicit types.

### Developer Experience & Safety

* **Predictability:** One documented precedence order; no surprises at runtime.
* **Observability:** You can answer “why did I get this value?” with SourceMap.
* **IDE & typing:** Rich hints and early failures instead of latent runtime errors.

### Team Ergonomics

* **Profiles in `pyproject.toml`:** Share stable defaults in‑repo; opt‑in personal/home profiles without forking code.
* **CI friendliness:** Env wins over files; programmatic can pin exact values in tests.

---

## Comparison with the Previous System

| Aspect              | Previous (env + context scope)                          | New (validated + profiles + freeze)                     |
| ------------------- | ------------------------------------------------------- | ------------------------------------------------------- |
| **Immutability**    | Ambient scope could be read late; risk of dynamic reads | Resolved once; `FrozenConfig` enters pipeline           |
| **Validation**      | Limited; mix of dict and dataclass consumers            | Strong schema validation; typed throughout              |
| **Sources**         | Env + ContextVar; no first‑class file profiles          | **Env + pyproject + home + defaults** with **profiles** |
| **Auditability**    | Implicit; hard to explain effective values              | **SourceMap** per field; redacted when surfaced         |
| **Extensibility**   | Adding fields required careful ad‑hoc wiring            | Schema‑driven; provider extras via **registry** seam    |
| **Testing**         | `config_scope()` convenient but mutable during run      | Scope only at **entry**; deterministic frozen snapshot  |
| **Team ergonomics** | No project/home profile story                           | First‑class project/home profiles; `POLLUX_PROFILE`     |

**Net effect:** Higher **clarity**, **predictability**, and **team usability**, with stronger **safety** and **observability**.

---

## Trade‑offs & Rejected Alternatives

* **Always‑live context layers during execution:** Rejected for runtime determinism and debuggability. We keep `config_scope()` but only **prior to** freezing.
* **Command‑embedded **only**, no resolver:** We adopt embedding via `FrozenConfig`, but keep a **dedicated resolver** for precedence/audit instead of pushing that burden onto callers.
* **Builder‑only approach:** Clear, but recreates validation/precedence logic already covered by the schema; acceptable as an optional wrapper, not the backbone.
* **Env‑only minimalism:** Simpler, but fails team use‑cases and audit requirements.

---

## Extension Points

* **Provider inference:** For custom rules, wrap `resolve_provider()` in your application or open an issue to discuss adding patterns upstream.
* **Extra field patterns:** Add or adjust `KNOWN_EXTRA_FIELDS` to document and validate conventional names.
* **File sources:** The TOML loader operates via **pure functions**; adding other sources (e.g., org policy file) fits naturally below env in precedence.
* **Schema evolution:** Add fields with defaults; use **Field aliases** and deprecation warnings for renames. The SourceMap helps detect unintended source shifts.
* **Path utilities:** `get_pyproject_path()` and `get_home_config_path()` functions provide clear extension points for alternative file locations.

---

## Observability & Security

* **Redaction:** Secrets (e.g., `api_key`) are never rendered in plaintext; audits show origin labels like `env:GEMINI_API_KEY`.
* **Metrics:** Emit counts per origin (how many fields from env/file/default) to spot misconfiguration or drift across environments.
* **Logging:** The resolver never logs raw secrets; audit dumps are explicit and opt‑in.

---

## Invariants & Properties (what we guarantee)

* **I1: Single resolution moment.** No handler observes a different config than another within the same command.
* **I2: Immutability.** Once frozen, config cannot be mutated (attempts raise).
* **I3: Precedence is per‑field.** Higher layers override only the fields they set.
* **I4: Auditability.** For any field, we can tell where the value came from.
* **I5: No hidden I/O.** Resolving config performs no network calls and touches only local files/env.

---

## Usage Notes

* **Configuration access:** Use `config.field` syntax with `FrozenConfig` instances for type-safe access to configuration values.
* **Scope usage:** Use `config_scope()` in tests or entry points; ensure resolution happens **before** building the initial command.
* **File adoption:** Add `[tool.pollux]` to `pyproject.toml`; introduce profiles under `[tool.pollux.profiles.<name>]`. Developers may keep a matching `~/.config/pollux.toml`.

---

## FAQ (Conceptual)

**Q: Can I change config mid‑run?**
No. Determinism and auditability depend on a single, frozen snapshot per command.

**Q: What if there is no `pyproject.toml`?**
Nothing breaks; env + defaults still work.

**Q: How do profiles interact with env vars?**
Env wins per field. Profiles fill gaps; they don’t fight env.

**Q: Will secrets appear in logs or audits?**
No. Only origin labels are exposed; raw values are redacted.

**Q: Where do provider‑specific knobs live?**
In a provider view constructed at the adapter boundary via the registry seam.

---

## Looking Ahead

* Optional **org‑level policy** source (lower than project) for enterprises.
* Structured **config diff** tooling to compare environments using SourceMap.
* Gradual tightening of schema (e.g., model/tier compatibility checks) as provider capabilities stabilize.
