# Configuration System — Deep Dive Specification

> Purpose: Precise, build-ready specification of the configuration subsystem.
> Scope: Data shapes, precedence algorithm, file formats, API surface, invariants, observability, testing, and migration.

---

## 1. Goals & Non‑Goals

### Goals

- **Resolve once, freeze then flow.** A single effective configuration is computed before pipeline entry using **Pydantic Two-File Core** pattern and attached to the initial command as `FrozenConfig`.
- **Predictable precedence.** Per‑field order: Programmatic → Env → Project file → Home file → Defaults.
- **Audit‑grade.** A per‑field SourceMap explains origins with comprehensive secret redaction (optional debug audit emission via warnings).
- **Provider inference.** Pattern-based mapping using compiled regex rules (`resolve_provider`).
- **Pattern-based validation.** Extra fields validation with non-breaking warnings for conventional naming patterns.
- **Async‑safe overrides.** `config_scope()` is an entry‑time convenience; never consulted during handler execution.

### Non‑Goals

- Hot reload; secrets manager integration; cross‑process globals; network I/O during resolution.

---

## 2. Boundaries & Responsibilities

| Concern                                | Library | User |
| -------------------------------------- | ------- | ---- |
| Precedence & merge                     | ✅       |      |
| Validation & types                     | ✅       |      |
| Supplying secrets                      |         | ✅    |
| File contents (`pyproject.toml`, home) |         | ✅    |
| Observability (metrics, audit)         | ✅       |      |
| Per-run overrides                      | ✅       | ✅    |

No network calls; resolution performs only local file reads and env access.

---

## 3. Data Model

### 3.1 Settings Schema (validation)

A **Pydantic BaseModel** (`Settings`) provides strong typing, field validation, automatic coercion, and cross-field rules. Uses **extra='allow'** to preserve unknown fields for extensibility.

**Canonical fields:**

- `api_key: str | None` — required iff `use_real_api=True`.
- `model: str = "gemini-2.0-flash"` — infers provider via pattern-based inference.
- `tier: APITier = APITier.FREE` — with explicit enum default.
- `enable_caching: bool = False`.
- `use_real_api: bool = False`.
- `ttl_seconds: int = 3600` (≥0).
- `telemetry_enabled: bool = False`.
- `request_concurrency: int = 6` (≥0) — client-side fan-out bound for vectorized calls.
  (Derived/runtime fields like `provider` and `extra` live on `FrozenConfig`, not on `Settings`.)

Schema provides automatic coercion from env strings and TOML types with clear error messages.

### 3.2 Pydantic Two-File Core Pattern

The system implements the **Pydantic Two-File Core** pattern:

1. **`Settings`** (mutable, validation) — Pydantic BaseModel for schema validation
2. **`FrozenConfig`** (immutable, runtime) — Frozen dataclass for pipeline flow

**Resolution flow:**

```text
Raw sources → Settings.model_validate() → FrozenConfig (frozen dataclass) → Pipeline
```

**SourceMap** tracks field origins separately for auditability without coupling to runtime payload.

### 3.3 FrozenConfig

A frozen dataclass carried on the command payload.

```python
@dataclass(frozen=True)
class FrozenConfig:
    model: str
    api_key: str | None
    use_real_api: bool
    enable_caching: bool
    ttl_seconds: int
    telemetry_enabled: bool
    tier: APITier
    request_concurrency: int
    provider: str  # Derived via pattern-based provider inference
    extra: dict[str, Any]  # Validated extra fields
```

### 3.4 Provider Inference

Provider is inferred from `model` using compiled regex patterns in priority order (exact names → version patterns → simple prefixes). The `resolve_provider(model)` helper encapsulates this mapping.

**Default rules** (checked in order):

- Exact model names (e.g., `gemini-1.5-flash`) → `google`
- Version patterns (e.g., `gemini-2.0-...`) → `google`
- Simple prefixes (`gemini-`) → `google`

### 3.5 Extra Fields Validation

**Pattern-based validation** for unknown fields with graceful degradation:

```python
@dataclass(frozen=True)
class ExtraFieldRule:
    pattern: str  # Regex pattern
    type_hint: type | str
    description: str
    deprecated: bool = False

def validate_extra_field(name: str, value: Any) -> list[str]:
    """Returns list of warning messages, empty if valid."""
```

**Conventional patterns:**

- `*_timeout` (int) — Timeout values in seconds
- `*_url` (str) — URL endpoints for external services
- `experimental_*` (Any) — Experimental features (unstable API)
- `legacy_*` (Any, deprecated) — Legacy fields for backward compatibility

### 3.6 Debug Audit Emission

Controlled via `POLLUX_DEBUG_CONFIG` and emitted through Python’s warnings module. By default, warnings print once per callsite; values are redacted to avoid secret leaks.

---

## 4. Sources & Precedence

**Order (highest → lowest):**

1. Programmatic overrides (dict passed to `resolve_config()` or via `with_overrides`)
2. Environment variables (`POLLUX_*`)
3. Project file: `./pyproject.toml`
4. Home file: `~/.config/pollux.toml`
5. Defaults (schema)

**Per‑field merge:** Higher layer sets a field → lower layers ignored for that field; unspecified fields fall through.

**Profiles:**

- Project file tables: `[tool.pollux]` and `[tool.pollux.profiles.<name>]`.
- Home file uses the same tables (`[tool.pollux]` and optional `[tool.pollux.profiles.<name>]`).
- Selection: `POLLUX_PROFILE=<name>` or `resolve_config(profile=...)`.

**.env support:** `resolve_config()` attempts to load a `.env` file if `python-dotenv` is available; failures are ignored for robustness.

---

## 5. File Formats

### 5.1 `pyproject.toml`

```toml
[tool.pollux]
model = "gemini-2.0-flash"
use_real_api = false
enable_caching = true
ttl_seconds = 3600

[tool.pollux.profiles.dev]
model = "gemini-2.0-flash"
use_real_api = false

[tool.pollux.profiles.prod]
model = "gemini-2.0-pro"
use_real_api = true
```

### 5.2 Home file `~/.config/pollux.toml`

```toml
[tool.pollux]
model = "gemini-2.0-flash"
tier = "FREE"

[tool.pollux.profiles.office]
model = "gemini-2.0-flash"
```

### 5.3 Parsing rules

- Use stdlib `tomllib` (Python 3.13+ required) — no fallback complexity.
- Malformed TOML returns empty dict with silent error handling for graceful degradation.
- Extra fields are **preserved** in `extra` dict and validated via pattern-based rules.
- Path utilities (`get_pyproject_path()`, `get_home_config_path()`) provide clear extension points.

---

## 6. Environment Variables

- Prefix: `POLLUX_` (e.g., `POLLUX_MODEL`, `POLLUX_TIER`).
- Field names are normalized to lower‑case after the prefix is stripped; variable names must match exactly.
- Type coercion: booleans (`true/false/1/0`), integers, enums (`APITier`).
- Also recognized: `GEMINI_API_KEY` (convenience; preferred if `POLLUX_API_KEY` is not set).
- Additional field: `POLLUX_REQUEST_CONCURRENCY` (int; default 6).

---

## 7. Resolution API

```python
def resolve_config(
    overrides: Mapping[str, Any] | None = None,
    profile: str | None = None,
    *,
    explain: bool = False,
) -> FrozenConfig | tuple[FrozenConfig, SourceMap]:
    """Merge inputs per precedence, validate via Pydantic, and return FrozenConfig.

    Raises:
        ValidationError: if Pydantic validation fails (clear error messages)
    """
```

```python
from contextlib import contextmanager

@contextmanager
def config_scope(
    cfg_or_overrides: Mapping[str, Any] | FrozenConfig | None = None,
    *, profile: str | None = None, **overrides
) -> Iterator[FrozenConfig]:
    ...  # Temporarily set scoped config for resolution time only
```

**Key enhancements:**

- **Pydantic validation** with clear error messages and field-level validation
- **Pattern-based provider inference** with priority regex rules
- **Extra fields validation** with pattern-based warnings
- **Environment-gated debug audit** (via warnings)
- Ambient scope affects **resolution time only**; handlers receive **FrozenConfig** snapshot

---

## 8. Algorithm (normative)

Enhanced algorithm using **Pydantic Two-File Core** pattern:

```python
def resolve_config(overrides=None, profile=None, *, explain=False):
    # 1) Load all sources
    merged, sources = _resolve_layers(
        overrides=(overrides or {}),
        env=load_env(),
        project=load_pyproject(profile=effective_profile),
        home=load_home(profile=effective_profile),
    )

    # 2) Pydantic validation with clear error messages
    try:
        settings = Settings.model_validate(merged)
    except ValidationError as e:
        raise e  # Pydantic provides clear field-level errors

    # 3) Provider inference
    provider = resolve_provider(settings.model)

    # 4) Create frozen config with extra fields validation
    frozen = _freeze(settings, provider, merged)

    # 5) Optional debug emission (warnings)
    if not explain and should_emit_debug():
        warnings.warn("Config audit...", stacklevel=2)

    return (frozen, sources) if explain else frozen

def _freeze(settings, provider, merged):
    # Extract and validate extra fields
    known_fields = set(Settings.model_fields.keys())
    extra = {k: v for k, v in merged.items() if k not in known_fields}
    _validate_extra_fields(extra)  # Pattern-based validation with warnings

    return FrozenConfig(
        provider=provider,
        extra=extra,
        **{field: getattr(settings, field) for field in known_fields}
    )
```

**Key enhancements:**

- **Pydantic validation** with rich error messages
- **Pattern-based provider inference**
- **Extra fields preservation** and pattern-based validation
- **Environment-gated debug audit** via warnings

---

## 9. Validation Rules

- If `use_real_api is True` ⇒ `api_key` must be non‑empty.
- `ttl_seconds >= 0`.
- Enum fields (e.g., `APITier`) must parse; error includes field path and offending value.

Errors abort resolution; callers may catch and surface actionable messages.

---

## 10. Observability & Audit

### 10.1 SourceMap

- `origin: Mapping[str, Origin]` where `Origin ∈ {default, home, project, env, overrides}`.
- **Redaction:** Never include raw secret values in `audit()`; show `env:GEMINI_API_KEY` etc.

### 10.2 Telemetry

- Emit counters (per field/per origin) and an overall summary (e.g., `n_env=3, n_file=2, n_default=1`).
- Optional non‑secret **config hash** for run correlation (exclude `api_key`).

---

## 11. Concurrency & Determinism

- `config_scope()` uses `ContextVar` to be **async‑safe**.
- Resolution happens **before** pipeline execution; the pipeline only sees `FrozenConfig`.
- Multiple executors/commands may carry different `FrozenConfig` values concurrently.

---

## 12. Security

- Do not log secrets; audits are origin‑only.
- File reading is local; no network; caller is responsible for file permissions.
- Provide a constant‑time redaction path in `audit()` to avoid accidental leaks.

---

## 13. Performance

- Resolution is O(fields + file size) and I/O‑light (two small TOML reads, optional `.env`).
- No caching across runs is required; callers can cache a `ResolvedConfig`/`FrozenConfig` explicitly if needed.

---

## 14. Testing Strategy

### Unit

- **Precedence:** Every field exercises all five layers; property test ensuring the highest non‑empty layer wins.
- **Validation:** Positive/negative tests for invariants; enum parsing.
- **Files:** Project vs home ordering; profile selection; malformed TOML.
- **Env:** Type coercion, case behavior, unknown keys policy.
- **Scope:** Nested scopes; async tasks receive independent ambient values.

### Integration

- **Freeze flow:** `ResolvedConfig → FrozenConfig → InitialCommand` and consumption in planner/executor.
- **Provider seam:** Adapter receives provider view; core stays neutral.

### Security

- **Redaction:** Ensure `api_key` never appears in audit/log output.

---

## 15. Migration & Compatibility

- **Phase 1:** Introduce resolver and `FrozenConfig`; leave dict reads in place with a warning log path.
- **Phase 2:** Codemod handler reads to attribute access; drop dict branch.
- **Phase 3:** Enable profiles and document `POLLUX_PROFILE`.
- **Deprecations:** Old field names may be kept as **aliases** with warnings for one minor version.

---

## 16. Acceptance Criteria

- Able to configure via env **or** files **or** programmatic args, with documented precedence.
- Missing required values fail **early** with actionable errors.
- `FrozenConfig` is present on the initial command and is **immutable**.
- SourceMap present and redacted; metrics emitted.
- No handler performs configuration I/O or resolves ambient values.

---

## 17. Future Work

- Optional org‑level policy file (lower than project) and enforcement hooks.
- Model/tier capability validation once provider capabilities stabilize.
- CLI: `pollux config --print-effective` (redacted) and `--check` for CI.
!!! note "Draft – pending revision"
    This specification will be reworked for clarity and efficacy. Included in nav for discoverability; content to be reviewed before release.

Last reviewed: 2025-09
