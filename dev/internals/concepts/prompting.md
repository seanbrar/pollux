# Prompting — Conceptual Overview

> Status: Accepted (initial version)
> Date: 2025-08-23
> Audience: Contributors and advanced users
> Position in Architecture: **A sub‑component of the Execution Planner** (prompt assembly stage), not a separate pipeline handler.

---

## Purpose

Provide a **simple, extensible, and audit‑grade** way to assemble prompts for batched requests. The system centralizes all prompt composition (system instruction + user prompts + light, source‑aware guidance) while preserving the **core batching invariants** and the **Command Pipeline** shape.

### Key outcomes

* Remove hard‑coded prompting from the planner’s control flow.
* Keep batching UX straightforward: the **number of user prompts** remains the driver of expected outputs.
* Allow **defaults** (library), **configuration overrides**, **file‑based prompts**, and an **advanced extension hook**.
* Ensure **cache determinism** and **clear telemetry**.

---

## Scope & Non‑Goals

### Scope

* Compose a **PromptBundle** (immutable):

  * `user: tuple[str, ...]` – transformed user prompts (prefix/suffix applied), count preserved.
  * `system: str | None` – optional system instruction.
  * `hints: Mapping[str, Any]` – small provenance flags (e.g., `has_sources`, `user_from`).
* Feed the bundle into the existing planner flow (token estimation, cache planning, API call preparation).

### Non‑Goals

* Response shaping, parsing, or schema validation (owned by **Result Builder**).
* Provider‑specific logic in the planner (remains in the adapter seam).
* Heavy templating/DSL or content inspection of sources.

---

## Architectural Placement

```text
Command → Source Handler → Execution Planner → API Handler → Result Builder → Result
                         └─► Prompt Assembler (this system)
```

* The Prompt Assembler is **pure** and **data‑driven**. It runs inside the Execution Planner before token estimation/plan finalization.
* It **does not** introduce a new handler nor cross the single SDK seam.

---

## Design Overview

### The PromptBundle (data model)

An immutable container that flows through the planner:

* **User prompts** are preserved in length; per‑prompt text may be wrapped (prefix/suffix).
* **System instruction** may be added without affecting counts.
* **Hints** track provenance and light context (e.g., `user_from=initial|user_file`, `system_from=inline|system_file`).

### Assembly Sources & Precedence

1. **Inline config** (preferred): `prompts.system`, `prompts.prefix`, `prompts.suffix`, `prompts.apply_if_sources`, `prompts.sources_block`.
2. **File inputs** (optional):

   * `prompts.system_file` – UTF‑8 text file for system instruction.
   * `prompts.user_file` – used **only** when `initial.prompts` is empty; yields exactly **one** user prompt.
3. **Advanced hook** (optional): `prompts.builder = "pkg.mod:fn"` – returns a `PromptBundle`; must be **pure** and adhere to invariants.

**System precedence:** `system (inline)` > `system_file` > `None`.

**User precedence:** if `initial.prompts` non‑empty → ignore `user_file` (telemetry notes `user_from=initial`); otherwise, read `user_file` and set `user=(text,)`.

### Source‑Aware Guidance

If `apply_if_sources=true` and sources are present, the assembler appends `sources_block` to the **system instruction** (never to the user prompts), keeping the output count invariant.

---

## Configuration Keys (summary)

```toml
[tool.pollux.prompts]
# System instruction
system = "You are a careful assistant…"        # optional
system_file = "prompts/system.txt"             # optional; used only if 'system' is unset

# Per‑prompt wrappers
prefix = "Answer concisely: "                   # default ""
suffix = ""                                    # default ""

# Source‑aware block
apply_if_sources = true                         # default false
sources_block = "Use the attached sources if relevant."  # optional

# User prompt from file (only if no runtime prompts are provided)
user_file = "prompts/query.txt"

# File reading guards
encoding = "utf-8"                             # default
strip = true                                    # chop trailing newlines
max_bytes = 128000                              # hard cap to avoid accidental huge files

# Advanced; dotted path to a pure builder function
# builder = "my_pkg.my_mod:build_prompts"
```

---

## Invariants & Properties

* **I1 – Count stability:** `expected_count == len(initial.prompts)` always holds. If `user_file` is used, `len(user)==1` by construction.
* **I2 – Purity & immutability:** Assembler is a pure function over `ResolvedCommand` + config snapshot; outputs an immutable bundle.
* **I3 – Cache determinism:** When present, `system` participates in the explicit **deterministic cache key** (alongside `joined_prompt` and source metadata).
* **I4 – Provider neutrality:** `system` is sent via a **neutral API config field**; adapters may use or ignore it without planner conditionals.
* **I5 – Observability:** Telemetry captures provenance (`user_from`, `system_from`, file paths), and sizes (`system_len`, `user_total_len`).

---

## Comparison with the Previous System

| Aspect           | Previous (implicit join in planner)      | New (Prompt Assembler)                                        |
| ---------------- | ---------------------------------------- | ------------------------------------------------------------- |
| System prompt    | Not modeled                              | First‑class (optional), included in cache key                 |
| User prompts     | Direct join; no wrappers                 | Prefix/suffix per prompt; count preserved                     |
| Source awareness | Inline conditionals in planner or absent | Declarative `apply_if_sources` + `sources_block`              |
| Config           | No dedicated section                     | `[prompts]` with clear fields; file inputs supported          |
| Extensibility    | Edit planner code                        | Optional dotted‑path builder hook                             |
| Observability    | Minimal                                  | Provenance & length metrics; deterministic cache key enriched |

**Net:** Cleaner separation of concerns, safer defaults for batching, and a single seam for advanced customization.

---

## Usage Examples

### 1) Simple

```python
cmd = InitialCommand(prompts=("What is the capital of France?",), sources=my_sources, config=frozen)
res = executor.execute(cmd)
```

`[prompts]` config may add a system instruction and a sources block; the count remains 1.

### 2) User prompt from file

```toml
[tool.pollux.prompts]
user_file = "prompts/query.txt"
```

```python
cmd = InitialCommand(prompts=(), sources=sources, config=frozen)
# assembler reads prompts/query.txt → user=("<file contents>",)
res = executor.execute(cmd)
```

### 3) Advanced builder

```toml
[tool.pollux.prompts]
builder = "my_pkg.my_mod:build_prompts"
```

```python
# my_pkg/my_mod.py
def build_prompts(command: ResolvedCommand) -> PromptBundle:
    # must be pure; do not perform I/O or network
    sys = "You are a helpful assistant."
    return PromptBundle(user=tuple(command.initial.prompts), system=sys, hints={"has_sources": bool(command.resolved_sources)})
```

---

## Observability

Emit the following planner metrics (names may vary slightly depending on your telemetry library):

* `planner.prompt.user_from` = `initial|user_file`
* `planner.prompt.system_from` = `inline|system_file|none`
* `planner.prompt.system_len` (int)
* `planner.prompt.user_total_len` (int)
* `planner.prompt.system_file`, `planner.prompt.user_file` (paths only)

---

## Security & Limits

* Files are read locally with size caps and strict decoding; errors raise `ConfigurationError`.
* No secrets should be embedded in prompt files; treat repository prompt files as regular text assets.

---

## Extension Points

* **Builder hook:** swap in custom assembler logic while respecting invariants.
* **Policy growth:** additional fields (e.g., tone/style) can be appended to `[prompts]` without planner changes.
* **Adapter support:** providers that can accept `system_instruction` consume it; others ignore it.

---

## FAQ

**Is this a new pipeline component?**
No. It’s a **stage inside the Execution Planner**. Keeping it internal preserves pipeline simplicity and avoids a second provider seam.

**Can I add multiple system prompts?**
No. The assembler produces at most one system instruction string. If you need composition, do it in your custom builder and yield a single string.

**Does using `user_file` change batching behavior?**
Only by defining one user prompt **when none were provided**. It never adds prompts on top of existing ones.
