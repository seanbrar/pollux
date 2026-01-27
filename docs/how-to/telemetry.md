# Telemetry Integration

Last reviewed: 2025-09

> Note: This page describes the current API. For the upcoming architecture, see Explanation → [Command Pipeline](../explanation/concepts/command-pipeline.md).

The library includes a `TelemetryContext` for advanced metrics collection. You can integrate it with your own monitoring systems (e.g., Prometheus, DataDog) by creating a custom reporter.

## Prerequisites

- Python 3.13 and `pollux` installed.
- Basic logging or a monitoring client available (for examples below, Python `logging`).
- Optional: set `POLLUX_TELEMETRY=1` to enable emission; otherwise the context becomes a no‑op.

This feature is designed for production environments where detailed telemetry is required. For design rationale and implementation details, see [Explanation → Concepts (Telemetry)](../explanation/concepts/telemetry.md), [Deep Dives → Telemetry Spec](../explanation/deep-dives/telemetry-spec.md), and [Decisions → ADR-0006 Telemetry](../explanation/decisions/ADR-0006-telemetry.md).

-----

## Quick Start (Production-Oriented)

Most users should either monitor logs or emit telemetry to an external backend. The built-in `_SimpleReporter` is useful for development, but is not recommended for regular use.

```python
import os
import logging
from typing import Any
from pollux.telemetry import TelemetryContext, TelemetryReporter

# 1) Enable telemetry via env (opt-in)
os.environ["POLLUX_TELEMETRY"] = "1"

# 2) Example: bridge timings/metrics to your existing logging setup
class LoggingReporter:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.log = logger or logging.getLogger("pollux.telemetry")

    def record_timing(self, scope: str, duration: float, **metadata: Any) -> None:
        self.log.info("telemetry.timing", extra={
            "scope": scope, "duration_s": duration, **metadata,
        })

    def record_metric(self, scope: str, value: Any, **metadata: Any) -> None:
        self.log.info("telemetry.metric", extra={
            "scope": scope, "value": value, **metadata,
        })

# 3) Install reporter
tele = TelemetryContext(LoggingReporter())

# 4) Your application code (the library emits scopes internally)
with tele("my.pipeline.step", batch_size=16):
    tele.gauge("token_efficiency", 0.92)
```

Success check:

- Expect INFO log lines containing `telemetry.timing` and `telemetry.metric` with your scopes and metadata.
- Programmatic check: `assert tele.is_enabled` and wrap a dummy scope to ensure your reporter receives events.

Notes:

- Prefer sending telemetry to a production backend (e.g., Prometheus, OpenTelemetry collector) rather than relying on a custom in-process reporter.
- If you only need human inspection, INFO logs with structured fields are often sufficient.

-----

## Implementing a Custom Reporter

You can create a custom reporter by creating a class that implements `record_timing` and/or `record_metric` methods.

Recommended — Structural typing (no inheritance):

```python
from typing import Any
from pollux.telemetry import TelemetryContext, TelemetryReporter

class MyCustomReporter:
    def record_timing(self, scope: str, duration: float, **metadata: Any) -> None:
        print(f"[TIMING] {scope} took {duration:.4f}s")

    def record_metric(self, scope: str, value: Any, **metadata: Any) -> None:
        print(f"[METRIC] {scope} = {value} ({metadata})")

reporter: TelemetryReporter = MyCustomReporter()  # Optional type annotation for IDEs/mypy
tele = TelemetryContext(reporter)
```

Optional — Runtime conformance check (when you accept reporters from third parties):

```python
from typing import Any
from pollux.telemetry import TelemetryContext, TelemetryReporter

class MyCustomReporter:
    def record_timing(self, scope: str, duration: float, **metadata: Any) -> None: ...
    def record_metric(self, scope: str, value: Any, **metadata: Any) -> None: ...

reporter = MyCustomReporter()
if not isinstance(reporter, TelemetryReporter):  # TelemetryReporter is @runtime_checkable
    raise TypeError("Reporter does not conform to TelemetryReporter protocol")

tele = TelemetryContext(reporter)
```

-----

## Integrating the Reporter

There are two ways to capture pipeline telemetry.

Option A — Enable built‑in telemetry via environment flags (no custom reporter):

- Set `POLLUX_TELEMETRY=1`. The library attaches a tiny, internal reporter and surfaces metrics into the `ResultEnvelope` (under `metrics` and `usage`).
- Read `env["metrics"]`/`env["usage"]` from the result. See Reference → [ResultEnvelope Metrics](../metrics.md) for shapes.

Option B — Provide your own reporter to the API handler in a custom pipeline:

```python
from __future__ import annotations
import logging
from typing import Any

from pollux.executor import GeminiExecutor
from pollux.config import resolve_config
from pollux.pipeline.source_handler import SourceHandler
from pollux.pipeline.planner import ExecutionPlanner
from pollux.pipeline.remote_materialization import RemoteMaterializationStage
from pollux.pipeline.rate_limit_handler import RateLimitHandler
from pollux.pipeline.cache_stage import CacheStage
from pollux.pipeline.api_handler import APIHandler
from pollux.pipeline.result_builder import ResultBuilder
from pollux.telemetry import TelemetryContext

class LoggingReporter:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.log = logger or logging.getLogger("pollux.telemetry")
    def record_timing(self, scope: str, duration: float, **metadata: Any) -> None:
        self.log.info("telemetry.timing", extra={"scope": scope, "duration_s": duration, **metadata})
    def record_metric(self, scope: str, value: Any, **metadata: Any) -> None:
        self.log.info("telemetry.metric", extra={"scope": scope, "value": value, **metadata})

cfg = resolve_config()
tele = TelemetryContext(LoggingReporter())  # requires POLLUX_TELEMETRY=1

handlers = [
    SourceHandler(),
    ExecutionPlanner(),
    RemoteMaterializationStage(),
    RateLimitHandler(),
    CacheStage(registries={}, adapter_factory=None),
    APIHandler(telemetry=tele, registries={"cache": None, "files": None}, adapter_factory=None),
    ResultBuilder(),
]

executor = GeminiExecutor(cfg, pipeline_handlers=handlers)
```

Notes

- Option A is simplest and surfaces metrics in the result envelope for immediate use.
- Option B streams timings/metrics to your backend via a reporter; it requires a custom executor and `POLLUX_TELEMETRY=1` to enable emission.

Verification

- Option A: run any `run_simple`/`run_batch` call and inspect `env["metrics"]` and `env["usage"]`.
- Option B: expect INFO log lines (or your backend events) with `telemetry.timing` and `telemetry.metric`.

-----

## Privacy and Data Handling

!!! warning "Handle data responsibly"
    - Avoid logging raw inputs, prompts, or secrets. Prefer IDs, short labels, and small scalar metadata in telemetry and logs.
    - Raw preview is sanitized and truncated by design, but still opt‑in. Enable only when necessary for triage and disable in steady‑state production.
    - Redaction: API keys and sensitive fields are never printed by `pollux-config`; apply the same discipline to your reporters and log processors.
    - Minimize retention: if exporting telemetry, keep payloads small and set retention appropriate to your compliance requirements.
    - PII: If processing personal data, align with your org’s policies (e.g., GDPR/CCPA). Do not include user content in telemetry; prefer anonymized counters and bounded metrics.

## Advanced Integration

The `TelemetryReporter` protocol is designed for flexibility:

- Multiple reporters: You can pass several reporters to the `TelemetryContext` factory, and each will receive all telemetry events.
- "Good Citizen" design: The system doesn't impose external library dependencies, allowing you to use your existing monitoring clients.
- Event metadata:
  - Timing events include: `depth`, `parent_scope`, `call_count`, and timing provenance (`start_monotonic_s`, `end_monotonic_s`, `start_wall_time_s`, `end_wall_time_s`).
  - Metric events include: `depth`, `parent_scope`, and your provided metadata.

Related:

- Concept → Telemetry: Scopes, Reporters, and Minimal Overhead: [explanation/concepts/telemetry.md](../explanation/concepts/telemetry.md)
- Decisions → ADR-0006 Telemetry: [explanation/decisions/ADR-0006-telemetry.md](../explanation/decisions/ADR-0006-telemetry.md)
- Reference → Telemetry API: [reference/api/telemetry.md](../reference/api/telemetry.md)
