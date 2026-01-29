# Error Handling Policy

This document explains how errors are validated, surfaced, and observed across the Pollux system. It provides concrete guidance and heuristics for implementers and extension authors to follow predictable, fail-fast behavior without over‑centralizing responsibilities.

## Principles

- Fail Fast: Enforce invariants at construction and architectural seams; reject invalid states immediately with a precise reason.
- Locality: Raise close to the source of the issue (constructor, stage, or seam) rather than deferring to downstream code.
- Predictability: Use consistent exception types and messages. Prefer explicit status and data over magic or heuristics.
- Observability: Emit small, structured telemetry; logs are advisory and opt‑in (debug level). Telemetry never breaks flows.

## Exception Taxonomy

- `ValueError` / `TypeError`: Field‑level validation failures in data classes and constructors (e.g., `ExtractionResult`).
- `InvariantViolationError`: Architectural contract violations at seams (e.g., invalid `ResultEnvelope`). Includes `stage_name` context.
- `PipelineError`: Operational/runtime failure from a stage (domain failure, not a contract breach).
- `PolluxError`: Base class for catching/reporting at top‑level when needed.

Use each where it brings the most clarity to the caller and keeps error context intact.

## Where to Validate

- Data Classes/Constructors (local):
  - Validate fields as early as possible and raise `ValueError`/`TypeError` with clear field context.
  - Use strict invariants; avoid implicit coercion in production paths.
  - Example: `ExtractionResult` requires `answers: list[str]` and `confidence ∈ [0,1]`.

- Architectural Seams (executor, conversation, devtools):
  - Validate envelopes and shapes at the boundary using a non‑raising predicate for ergonomics.
  - On failure, raise `InvariantViolationError` with a concise reason and `stage_name`.
  - Increment telemetry counters for invariant violations.

- Stage Internals:
  - If a stage cannot produce a valid result for domain reasons, return a `Failure` with a clear message.
  - Contract/shape issues should be prevented earlier; avoid “fixing” invalid states deep in the pipeline.

## Result Envelope Contract

- Always present: `status`, `answers`, `extraction_method`, `confidence`.
- `status`: one of `"ok" | "partial" | "error"`.
- `answers`: `list[str]` (padded/truncated by ResultBuilder to the expected count).
- `extraction_method`: non‑empty `str`.
- `confidence`: `float` in `[0.0, 1.0]`.

Centralized validation (non‑raising):

```python
from pollux.core.result_envelope import explain_invalid_result_envelope
from pollux.core.types import is_result_envelope

reason = explain_invalid_result_envelope(obj)
if reason is not None:
    # invalid shape; raise at seam with stage context
    raise InvariantViolationError(reason, stage_name="conversation")
```

Notes:

- The core envelope validator enforces presence and range of `confidence`.
- The TypeGuard `is_result_envelope` uses the same source of truth (fast path) for ergonomic narrowing.

## Conversation Error Semantics

- Derive error strictly from `status`:
  - `status == "error"` → error turn.
  - `status == "ok" | "partial"` → non‑error turn (partial handled by UI/consumers as appropriate).
- Do not rely on legacy `ok`/`error` flags; envelopes must validate first. Invalid envelopes fail fast.

## Logging and Telemetry

- Logging: Use debug logs for advisory/dev‑only hints (e.g., normalization advisories). Never rely on logs for correctness.
- Telemetry:
  - Increment `pipeline.invariant_violation` when a contract is breached at a seam.
  - Increment `pipeline.error` for stage `Failure` results.
  - Attach stage durations; avoid mutating core fields. Best‑effort metrics attachment must never raise.

## Heuristics Checklist

- When adding a field to a data class, ask: can an invalid value be constructed? If yes, validate in `__post_init__` and raise immediately.
- When adding an API seam or terminal stage, ask: what is the minimal valid shape? Validate at the seam before usage; raise `InvariantViolationError` with `stage_name`.
- Avoid dual sources of truth for the same invariant. If layering is intentional (e.g., strict constructor + seam validator), document the rationale.
- Prefer explicitness over magic: rely on `status` (not heuristics) for error detection.
- Don’t log and continue on invariant breaches; raise deterministically or return `Failure`.

## Examples

- Validating at a seam (Conversation):

```python
res = await executor.execute(cmd)
if not is_result_envelope(res):
    reason = explain_invalid_result_envelope(res) or "Invalid ResultEnvelope"
    raise InvariantViolationError(reason, stage_name="conversation")

is_error = (res["status"].lower() == "error")
answers = tuple(res.get("answers", ()))
```

- Data class strict validation (constructor):

```python
@dataclass(frozen=True)
class ExtractionResult:
    answers: list[str]
    method: str
    confidence: float

    def __post_init__(self) -> None:
        if not isinstance(self.answers, list):
            raise ValueError("answers must be a list")
        if not self.method:
            raise ValueError("method cannot be empty")
        cf = float(self.confidence)
        if not (0.0 <= cf <= 1.0):
            raise ValueError("confidence must be in [0.0, 1.0]")
```

## Guidance for Extension Authors

- Extractors must return `answers: list[str]` and `confidence` within `[0,1]`.
- If building custom terminal stages, always construct a fully valid `ResultEnvelope` upfront; do not rely on downstream correction.
- Validate at your boundary; fail fast with clear messages. Use `InvariantViolationError` for contract breaches.
- Avoid legacy fields for error/ok; set `status` explicitly and consistently.

## Summary

- Use local `ValueError`/`TypeError` for field invariants.
- Use non‑raising validation + `InvariantViolationError` at seams.
- Derive errors from `status` only; keep logs advisory and telemetry minimal.
- The core envelope validator is the single source of truth for envelope shape and `confidence` range.
