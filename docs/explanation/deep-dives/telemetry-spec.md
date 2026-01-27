# Telemetry Spec

This deep dive documents the Telemetry system’s behavior, interfaces, and performance characteristics for contributors and advanced users.

## Goals

- Provide structured, hierarchical timing and metric events.
- Ensure negligible overhead when disabled.
- Keep the system runtime-independent and protocol-based for reporter flexibility.

## Architecture

### Factory and Contexts

- `TelemetryContext(*reporters)` is the entry point.
  - If `POLLUX_TELEMETRY=1` or `DEBUG=1` and at least one reporter is provided, returns `_EnabledTelemetryContext`.
  - Otherwise returns `_NO_OP_SINGLETON` of `_NoOpTelemetryContext`.

### Enabled Context

- Callable and a context manager: `with tele("scope", **metadata): ...`
- Tracks nested scopes using `ContextVar`:
  - `_scope_stack_var: ContextVar[tuple[str, ...]]`
  - `_call_count_var: ContextVar[int]`
- Captures timestamps with `time.perf_counter()` and `time.time()` to compute durations and provide correlation-friendly wall time.
- Emits timing events with metadata:
  - `depth`, `parent_scope`, `call_count`, `start_monotonic_s`, `end_monotonic_s`, `start_wall_time_s`, `end_wall_time_s` plus any user-provided metadata.
- Metric helpers:
  - `metric(name, value, **metadata)` (base)
  - `count(name, increment=1, **metadata)` (sets `metric_type="counter"`)
  - `gauge(name, value, **metadata)` (sets `metric_type="gauge"`)
  - Metric events include `depth`, `parent_scope` in addition to user metadata.

### No-Op Context

- Immutable, stateless object with the same interface.
- All methods perform no work and return immediately.
- Allows unconditional calls in code paths without branches.

## Reporters

- Protocol-based (`TelemetryReporter`) with two methods:
  - `record_timing(scope: str, duration: float, **metadata)`
  - `record_metric(scope: str, value: Any, **metadata)`
- Reporters should be fast and non-blocking. Failures are caught and logged; they must not break core execution.
- Multiple reporters are supported; each receives all events.

## Scope Naming and Validation

- Recommended schema: `lowercase` segments separated by dots with digits/underscores allowed.
- Optional strict regex validation via `POLLUX_TELEMETRY_STRICT_SCOPES=1`.

## Performance Considerations

- Disabled path: no-op singleton avoids allocations and function work; method calls are near-zero overhead.
- Enabled path: duration captured with two monotonic reads and a wall clock call; minimal allocations for metadata dict and reporter dispatch.
- Hot paths can check `tele.is_enabled` to skip expensive metadata assembly.

## Development Tools

- `_SimpleReporter`: in-memory reporter for local debugging.
  - Not part of the public API; import from `pollux.telemetry` as an internal.
  - Helpers: `print_report()`, `as_dict()`, `reset()`.
  - Produces a hierarchical summary of timings and totals for quick inspection.

Example usage:

```python
import os
os.environ["POLLUX_TELEMETRY"] = "1"

from pollux.telemetry import _SimpleReporter, TelemetryContext

reporter = _SimpleReporter()
tele = TelemetryContext(reporter)

with tele("test.operation", extra="debug"):
    tele.count("items_processed", increment=3)

reporter.print_report()
snapshot = reporter.as_dict()
reporter.reset()
```

## Backward Compatibility

- Deprecated alias: `tele_scope(ctx, name, **metadata)` forwards to calling the context directly.
- Existing usage should move to `with tele("scope"):`. The alias will be removed in a future major version.

## Examples

```python
from pollux.telemetry import TelemetryContext, TelemetryReporter

class PrintReporter(TelemetryReporter):
    def record_timing(self, scope: str, duration: float, **metadata):
        print("timing", scope, duration, metadata)

    def record_metric(self, scope: str, value: object, **metadata):
        print("metric", scope, value, metadata)

tele = TelemetryContext(PrintReporter())
with tele("pipeline.plan", batch_size=32):
    tele.count("api.requests", increment=1)
    tele.gauge("token_efficiency", 0.91)
```

## Related

- [Concept → Telemetry: Scopes, Reporters, and Minimal Overhead](../concepts/telemetry.md)
- [Decisions → ADR-0006 Telemetry](../decisions/ADR-0006-telemetry.md)
- [Reference → Telemetry API](../../reference/api/telemetry.md)

## Performance benchmarks

To validate the “negligible overhead when disabled” and characterize enabled performance:

- Disabled overhead target: <200ns per scope operation
- Enabled throughput target: >100k scope ops/sec (no-op reporter)
- Memory growth: ~<100 bytes per nested level

Benchmarks use a no-op reporter to isolate framework cost. Enable telemetry via `POLLUX_TELEMETRY=1` (or `DEBUG=1`) when running enabled tests. Internal scripts under `dev/benchmarks/` are provided for contributors; results should be summarized (not raw runs) in PRs that change telemetry internals.
