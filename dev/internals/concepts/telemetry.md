# Telemetry: Scopes, Reporters, and Minimal Overhead

Telemetry in Pollux is an extension point that gives users fine-grained metrics with negligible overhead when disabled. It is designed to be simple to adopt, safe in concurrent contexts, and easy to extend without pulling in heavyweight dependencies.

## What Telemetry Provides

- **Contextual scopes**: Use hierarchical, dot-separated scope names (e.g., `pipeline.plan.tokens`) to organize timing and metrics.
- **Minimal overhead guarantee**: When disabled, the system returns a shared no-op context so calls are effectively inert.
- **Flexible reporters**: Implement two simple methods to send data anywhere (Prometheus, StatsD, custom stores) without depending on external libraries.
- **Thread/async safety**: Uses `contextvars.ContextVar` to track nested scopes and metadata without shared mutable state.

## Core Abstractions

- **TelemetryContext**: A factory that returns either a fully featured context (enabled) or a shared no-op instance (disabled). The context is callable and also acts as a context manager.
  - Enabled when an env flag is set (`POLLUX_TELEMETRY=1` or `DEBUG=1`) and at least one reporter is provided.
  - Offers helpers: `time(name)`, `count(name, increment=1, **metadata)`, `gauge(name, value, **metadata)`.

- **TelemetryReporter**: A structural protocol with two methods:
  - `record_timing(scope: str, duration: float, **metadata)`
  - `record_metric(scope: str, value: Any, **metadata)`
  Implement these methods in your reporter; no inheritance is required.

## Scope and Metadata Model

- Scopes are dot-separated lowercase tokens. Optional strict validation can enforce a regex at runtime.
- Timing events include: `depth`, `parent_scope`, `call_count`, and timing provenance (`start_monotonic_s`, `end_monotonic_s`, `start_wall_time_s`, `end_wall_time_s`).
- Metric events include: `depth`, `parent_scope`. The `metric_type` is set for `count(...)` and `gauge(...)` helpers.

## Why This Design

- **Simplicity**: Clear, minimal API that fits Python’s structural typing model.
- **Performance**: No runtime branches sprinkled throughout code; the factory decides once, and no-op calls are nearly free.
- **Extensibility**: Reporters are user-owned and can integrate with any observability stack.
- **Safety**: Context-local state prevents cross-talk between concurrent operations.

## When to Use It

- Production telemetry: Measure handler latency, API durations, and batch performance.
- Developer diagnostics: Enable locally with a simple in-memory reporter during performance investigations.

## Related

- [Deep Dive — Telemetry Spec](../deep-dives/telemetry-spec.md)
- [ADR-0006 — Telemetry](../decisions/ADR-0006-telemetry.md)
- [Architecture at a Glance](../architecture.md)

## Raw Preview (Research)

For debugging and research, you can opt in to attach a compact, sanitized preview of provider responses into the result envelope (`metrics.raw_preview`). Enable globally with `POLLUX_TELEMETRY_RAW_PREVIEW=1` or per handler via `APIHandler(include_raw_preview=True)`. See the Telemetry Guide for examples and field details.
