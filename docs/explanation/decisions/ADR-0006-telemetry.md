# ADR-0006: Telemetry Context and Reporter Protocol

**Date:** 2025-08-18
**Status:** Accepted
**Tags:** observability, performance, extensibility
**Audience:** Contributors and operators
**Impacted Modules/APIs:** `TelemetryContext`, `TelemetryReporter` protocol, telemetry scope naming

---

## Context

We need rich, contextual metrics across the pipeline (planning, API calls, result shaping) that are:

- Safe to call unconditionally, even in hot paths.
- Easy for users to integrate with diverse monitoring stacks.
- Clear and minimal in API surface to preserve architectural simplicity.

Earlier designs mixed ad-hoc timing, logging, and counters throughout classes, yielding inconsistent context and higher maintenance cost.

---

## Decision

Introduce a `TelemetryContext` factory and a `TelemetryReporter` protocol:

- `TelemetryContext(*reporters)` returns either:
  - An enabled context when env flag is on (`POLLUX_TELEMETRY=1` or `DEBUG=1`) and reporters exist; or
  - A shared no-op singleton when disabled.
- `TelemetryReporter` defines two methods: `record_timing` and `record_metric`.
- The context enriches timing events with depth, parent scope, call count, and precise start/end times.
- The context supports `count` and `gauge` helpers for common metric types.

---

## Rationale

- **Negligible overhead**: No-op singleton lets us instrument without runtime branching.
- **Extensibility**: Protocol-based reporters keep the core free of vendor libraries and let users plug in their own clients.
- **Clarity**: Scopes and metadata unify how we capture context across handlers.
- **Safety**: Context-local state via `ContextVar` is concurrency-friendly.

---

## Consequences

Positive:

- Consistent, structured telemetry across the pipeline.
- Easy integration with existing observability systems.
- Improved diagnostics without sacrificing performance.

Negative:

- Additional concepts for contributors to learn (scopes, reporters).
- Potential to over-instrument if naming guidance is ignored; strict validation is optional to mitigate.

---

## Alternatives Considered

- **Global metrics client**: Simple to wire but couples the library to a specific vendor and complicates testing.
- **Decorators on functions**: Useful but less flexible for mid-function segments and dynamic scope metadata.
- **Context managers only**: Insufficient for non-timing metrics (`count`, `gauge`).

---

## Adoption

- Re-export `TelemetryContext` and `TelemetryReporter` at the package root to improve ergonomics.
- Document scope naming conventions and optional strict validation.
- Provide development-only `_SimpleReporter` to aid local diagnostics.

---

## References

- [Concept – Telemetry: Scopes, Reporters, and Minimal Overhead](../concepts/telemetry.md)
- [Deep Dive – Telemetry Spec](../deep-dives/telemetry-spec.md)
- [Reference – Telemetry API](../../reference/api/telemetry.md)
- [Project History](../history.md)
