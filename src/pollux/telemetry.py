"""Telemetry context and reporter interfaces.

Provides ultra-low overhead no-op behavior when disabled and rich, contextual
metrics when enabled via environment flags.
"""

from collections import deque
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import logging
import os
import re
import time
from types import TracebackType
from typing import Any, Final, Protocol, Self, TypedDict, runtime_checkable
from warnings import deprecated

log = logging.getLogger(__name__)

# Context-aware state for thread/async safety
_scope_stack_var: ContextVar[tuple[str, ...]] = ContextVar(
    "scope_stack",
    default=(),
)
_call_count_var: ContextVar[int] = ContextVar("call_count", default=0)

# Minimal-overhead optimization - evaluated once at import time
# Telemetry is enabled only via explicit env toggle to avoid unintended overhead
_TELEMETRY_ENABLED = os.getenv("POLLUX_TELEMETRY") == "1"
_STRICT_SCOPES = os.getenv("POLLUX_TELEMETRY_STRICT_SCOPES") == "1"

# Built-in metadata keys (exported for clarity & resilience)
DEPTH: Final[str] = "depth"
PARENT_SCOPE: Final[str] = "parent_scope"
CALL_COUNT: Final[str] = "call_count"
METRIC_TYPE: Final[str] = "metric_type"
START_MONOTONIC_S: Final[str] = "start_monotonic_s"  # High-precision monotonic seconds
END_MONOTONIC_S: Final[str] = "end_monotonic_s"
START_WALL_TIME_S: Final[str] = "start_wall_time_s"  # Epoch seconds (correlation)
END_WALL_TIME_S: Final[str] = "end_wall_time_s"

_SCOPE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


class _TelemetryMetadata(TypedDict, total=False):
    depth: int
    call_count: int
    parent_scope: str | None
    start_monotonic_s: float
    end_monotonic_s: float
    start_wall_time_s: float
    end_wall_time_s: float


@runtime_checkable
class TelemetryReporter(Protocol):
    """Duck-typed protocol for telemetry reporters."""

    def record_timing(self, scope: str, duration: float, **metadata: Any) -> None: ...  # noqa: D102
    def record_metric(self, scope: str, value: Any, **metadata: Any) -> None: ...  # noqa: D102


@dataclass(frozen=True, slots=True)
class _NoOpTelemetryContext:
    """An immutable and stateless no-op context, optimized for negligible overhead."""

    def __call__(self, name: str, **metadata: Any) -> Self:  # noqa: ARG002
        return self  # Self is already a context manager

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _: type[BaseException] | None,
        __: BaseException | None,
        ___: TracebackType | None,
    ) -> bool | None:
        return None

    @property
    def is_enabled(self) -> bool:
        return False

    def metric(self, name: str, value: Any, **metadata: Any) -> None:
        pass

    def time(self, name: str, **metadata: Any) -> Self:  # noqa: ARG002
        return self

    def count(self, name: str, increment: int = 1, **metadata: Any) -> None:
        pass

    def gauge(self, name: str, value: float, **metadata: Any) -> None:
        pass


class _EnabledTelemetryContext:
    """Full-featured telemetry context when enabled."""

    __slots__ = ("reporters",)

    def __init__(self, *reporters: TelemetryReporter):
        self.reporters = reporters

    def __call__(
        self, name: str, **metadata: Any
    ) -> AbstractContextManager["_EnabledTelemetryContext"]:
        return self._create_scope(name, **metadata)

    @contextmanager
    def _create_scope(
        self, name: str, **metadata: Any
    ) -> Iterator["_EnabledTelemetryContext"]:
        """The actual scope implementation when enabled."""
        if not name or not isinstance(name, str):
            raise ValueError("Scope name must be a non-empty string")
        if _STRICT_SCOPES and not _SCOPE_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                "Invalid scope name. Use lowercase letters, digits, and underscores; "
                "segments separated by dots.",
            )

        scope_stack = _scope_stack_var.get()
        call_count = _call_count_var.get()
        scope_path = ".".join((*scope_stack, name))
        start_monotonic_s = time.perf_counter()
        start_wall_time_s = time.time()

        scope_token = _scope_stack_var.set((*scope_stack, name))
        count_token = _call_count_var.set(call_count + 1)

        try:
            yield self  # Return self so chained methods work
        finally:
            end_monotonic_s = time.perf_counter()
            duration = end_monotonic_s - start_monotonic_s
            end_wall_time_s = start_wall_time_s + duration
            _scope_stack_var.reset(scope_token)
            _call_count_var.reset(count_token)

            final_stack = _scope_stack_var.get()
            final_count = _call_count_var.get()

            built: _TelemetryMetadata = {
                "depth": len(final_stack),
                "call_count": final_count,
                "parent_scope": ".".join(final_stack) if final_stack else None,
                "start_monotonic_s": start_monotonic_s,
                "end_monotonic_s": end_monotonic_s,
                "start_wall_time_s": start_wall_time_s,
                "end_wall_time_s": end_wall_time_s,
            }
            enhanced_metadata: dict[str, Any] = {**built, **metadata}

            for reporter in self.reporters:
                try:
                    reporter.record_timing(scope_path, duration, **enhanced_metadata)
                except Exception as e:
                    log.error(
                        "Telemetry reporter '%s' failed: %s",
                        type(reporter).__name__,
                        e,
                        exc_info=True,
                    )

    def metric(self, name: str, value: Any, **metadata: Any) -> None:
        """Record a metric within current scope context."""
        scope_stack = _scope_stack_var.get()
        scope_path = ".".join((*scope_stack, name))
        built: _TelemetryMetadata = {
            "depth": len(scope_stack),
            "parent_scope": ".".join(scope_stack) if scope_stack else None,
        }
        enhanced_metadata: dict[str, Any] = {**built, **metadata}
        for reporter in self.reporters:
            try:
                reporter.record_metric(scope_path, value, **enhanced_metadata)
            except Exception as e:
                log.error(
                    "Telemetry reporter '%s' failed: %s",
                    type(reporter).__name__,
                    e,
                    exc_info=True,
                )

    # Convenience methods for chaining
    def time(
        self, name: str, **metadata: Any
    ) -> AbstractContextManager["_EnabledTelemetryContext"]:
        """Alias for scope() - more intuitive for timing operations."""
        return self(name, **metadata)

    def count(self, name: str, increment: int = 1, **metadata: Any) -> None:
        """Record a counter metric."""
        self.metric(name, increment, metric_type="counter", **metadata)

    def gauge(self, name: str, value: float, **metadata: Any) -> None:
        """Record a gauge metric."""
        self.metric(name, value, metric_type="gauge", **metadata)

    @property
    def is_enabled(self) -> bool:
        return True


_NO_OP_SINGLETON = _NoOpTelemetryContext()

type TelemetryContextProtocol = _EnabledTelemetryContext | _NoOpTelemetryContext


def TelemetryContext(*reporters: TelemetryReporter) -> TelemetryContextProtocol:  # noqa: N802
    """Return a telemetry context.

    Behavior:
    - When telemetry env flags are enabled (``POLLUX_TELEMETRY=1``),
      return an enabled context. If no reporters are provided, install a default
      in-memory ``_SimpleReporter`` for convenience.
    - When telemetry env flags are disabled, return a shared no-op instance for
      negligible overhead.
    """
    if _TELEMETRY_ENABLED:
        reps = reporters or (_SimpleReporter(),)
        return _EnabledTelemetryContext(*reps)
    # Always return the same, pre-existing no-op instance.
    return _NO_OP_SINGLETON


@deprecated("Use ctx(name, **metadata) instead")
def tele_scope(
    ctx: TelemetryContextProtocol,
    name: str,
    **metadata: Any,
) -> AbstractContextManager["_EnabledTelemetryContext"] | _NoOpTelemetryContext:
    """Deprecated wrapper that forwards to the context callable."""
    return ctx(name, **metadata)


class _SimpleReporter:
    """Built-in reporter for development use.

    This reporter collects metrics in memory. To view the collected data,
    call the `get_report()` method and print the result.
    """

    def __init__(self, max_entries_per_scope: int = 1000):
        self.max_entries = max_entries_per_scope
        self.timings: dict[str, deque[tuple[float, dict[str, Any]]]] = {}
        self.metrics: dict[str, deque[tuple[Any, dict[str, Any]]]] = {}

    def record_timing(self, scope: str, duration: float, **metadata: Any) -> None:
        if scope not in self.timings:
            self.timings[scope] = deque(maxlen=self.max_entries)
        self.timings[scope].append((duration, metadata))

    def record_metric(self, scope: str, value: Any, **metadata: Any) -> None:
        if scope not in self.metrics:
            self.metrics[scope] = deque(maxlen=self.max_entries)
        self.metrics[scope].append((value, metadata))

    def print_report(self) -> None:
        """Prints the report to stdout if any data was collected."""
        if self.timings or self.metrics:
            print(self.get_report())  # noqa: T201

    def reset(self) -> None:
        """Clear all collected telemetry (testing convenience)."""
        self.timings.clear()
        self.metrics.clear()

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of collected data (testing)."""
        return {
            "timings": {key: list(values) for key, values in self.timings.items()},
            "metrics": {key: list(values) for key, values in self.metrics.items()},
        }

    def get_report(self) -> str:
        """Generate hierarchical telemetry report."""
        lines = ["=== Telemetry Report ===\n"]

        # Group by hierarchy
        timing_tree = self._build_hierarchy(self.timings)
        self._format_tree(timing_tree, lines, "Timings")

        if self.metrics:
            lines.append("\n--- Metrics ---")
            for scope, values in sorted(self.metrics.items()):
                total = sum(v[0] for v in values if isinstance(v[0], int | float))
                lines.append(
                    f"{scope:<40} | Count: {len(values):<4} | Total: {total:,.0f}",
                )

        return "\n".join(lines)

    def _build_hierarchy(
        self,
        data: dict[str, deque[tuple[float, dict[str, Any]]]],
    ) -> dict[str, Any]:
        """Build tree structure from dot-separated scope names."""
        tree: dict[str, Any] = {}
        for scope, values in data.items():
            parts = scope.split(".")
            current = tree
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = values
        return tree

    def _format_tree(
        self,
        tree: dict[str, Any],
        lines: list[str],
        title: str,
        depth: int = 0,
    ) -> None:
        """Format hierarchical tree with indentation."""
        if depth == 0:
            lines.append(f"\n--- {title} ---")

        for key, value in sorted(tree.items()):
            indent = "  " * depth
            if isinstance(value, dict):
                lines.append(f"{indent}{key}:")
                self._format_tree(value, lines, title, depth + 1)
            else:
                # Leaf node - actual timing data
                durations = [v[0] for v in value]
                avg_time = sum(durations) / len(durations)
                total_time = sum(durations)
                lines.append(
                    f"{indent}{key:<30} | "
                    f"Calls: {len(durations):<4} | "
                    f"Avg: {avg_time:.4f}s | "
                    f"Total: {total_time:.4f}s",
                )
