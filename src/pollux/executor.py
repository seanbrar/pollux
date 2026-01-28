"""The primary user-facing entry point for the pipeline.

This module keeps runtime logic simple and explicit. The executor guarantees
correctness by enforcing a final `ResultEnvelope` invariant. Additional
dev-time validation can be enabled without impacting production flows.

Telemetry note: the executor records per-stage durations during execution. If
the terminal stage does not surface these durations into the final envelope's
`metrics` (e.g., a custom terminal stage instead of `ResultBuilder`), the
executor will attach a best-effort `metrics.durations` map post-invariant
without overwriting any existing values.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path as _Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

from pollux._dev_flags import dev_validate_enabled
from pollux.config import FrozenConfig, resolve_config
from pollux.core import types as _ctypes
from pollux.core.exceptions import (
    InvariantViolationError,
    PipelineError,
    PolluxError,
)
from pollux.core.types import (
    Failure,
    FinalizedCommand,
    InitialCommand,
    Result,
    ResultEnvelope,
    Success,
    is_result_envelope,
)
from pollux.pipeline._erasure import (
    ErasedAsyncHandler,
    erase,
)
from pollux.pipeline.api_handler import APIHandler
from pollux.pipeline.cache_stage import CacheStage
from pollux.pipeline.planner import ExecutionPlanner
from pollux.pipeline.rate_limit_handler import RateLimitHandler
from pollux.pipeline.registries import CacheRegistry, FileRegistry
from pollux.pipeline.remote_materialization import RemoteMaterializationStage
from pollux.pipeline.result_builder import ResultBuilder
from pollux.pipeline.source_handler import SourceHandler
from pollux.telemetry import TelemetryContext

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pollux.pipeline.base import BaseAsyncHandler


class GeminiExecutor:
    """Executes commands through a pipeline of handlers.

    This class manages the flow of commands through a series of processing
    stages, each responsible for a specific aspect of the request.

    Notes on validation and invariants:
    - The executor guarantees correctness by enforcing that the final value
      is a `ResultEnvelope`-shaped dict. This is the authoritative invariant.
    - The optional `validate` flag is for development-time ergonomics only
      (richer shape checks and diagnostics). It does not change the runtime
      contract and defaults to the `POLLUX_PIPELINE_VALIDATE=1` environment
      toggle when not provided.
    """

    def __init__(
        self,
        config: FrozenConfig,
        pipeline_handlers: (
            Iterable[BaseAsyncHandler[Any, Any, PolluxError]]
            | Iterable[ErasedAsyncHandler]
            | None
        ) = None,
        *,
        validate: bool | None = None,
    ):
        """Initialize the executor with configuration.

        Args:
            config: Configuration for the pipeline (FrozenConfig).
            pipeline_handlers: Optional list of handlers to override the default pipeline.
            validate: Enable dev-time validation (overrides POLLUX_PIPELINE_VALIDATE).
        """
        self.config = config
        self._cache_registry = CacheRegistry()
        self._file_registry = FileRegistry()
        # Dev-only validation flag for stricter checks in development.
        # Correctness is guaranteed by the executor's final invariant.
        self._validate_pipeline: bool = dev_validate_enabled(override=validate)
        # Build or validate a raw pipeline for tests and introspection
        raw_handlers: list[Any] = list(
            pipeline_handlers or self._build_default_pipeline(config)
        )
        if not raw_handlers:
            raise ValueError("Pipeline may not be empty; provide at least one handler.")
        self._pipeline = raw_handlers
        # Internal execution pipeline (type-erased wrappers). Supports mixed inputs.
        self._exec_pipeline: list[ErasedAsyncHandler] = [
            erase(h) for h in self._pipeline
        ]

    def _build_default_pipeline(self, config: FrozenConfig) -> list[Any]:
        """Build the default pipeline of handlers.

        Returns:
            The list of handlers that comprise the default pipeline.
        """
        # Optional real adapter factory when explicitly requested
        adapter_factory = None
        if config.use_real_api:
            # Use the provider adapter seam to get the right configuration
            from pollux.pipeline.adapters.registry import build_provider_config

            _ = build_provider_config(config.provider, config)

            def _factory(api_key: str) -> Any:  # defer import until needed
                from pollux.pipeline.adapters.gemini import GoogleGenAIAdapter

                return GoogleGenAIAdapter(api_key)

            adapter_factory = _factory

        # Always include the RateLimitHandler. Enforcement is plan-driven:
        # the planner attaches a RateConstraint only when using the real API.
        # When no constraint is present, the handler is a no-op.
        handlers: list[Any] = [
            SourceHandler(),
            ExecutionPlanner(),
            RemoteMaterializationStage(),
            RateLimitHandler(),
        ]

        handlers += [
            CacheStage(
                registries={
                    "cache": self._cache_registry,
                },
                adapter_factory=adapter_factory,
            ),
            APIHandler(
                telemetry=None,
                registries={
                    "cache": self._cache_registry,
                    "files": self._file_registry,
                },
                adapter_factory=adapter_factory,
            ),
            ResultBuilder(
                validate=self._validate_pipeline,
                allow_upstream_diagnostics=True,
            ),
        ]
        return handlers

    async def execute(self, _command: InitialCommand) -> ResultEnvelope:
        """Execute a command through the pipeline.

        Args:
            _command: The initial command to execute (sources, prompts, config).

        Returns:
            A minimal result dictionary produced by the `ResultBuilder` stage.

        Raises:
            PipelineError: If any stage returns a failure result.
        """
        # Sequentially run through the pipeline with explicit Result handling
        current: Any = _command
        last_stage_name = None
        stage_durations: dict[str, float] = {}
        ctx = TelemetryContext()  # no-op unless enabled with reporters/env

        for handler in self._exec_pipeline:
            last_stage_name = handler.stage_name
            with ctx("pipeline.stage", stage=last_stage_name):
                start = perf_counter()
                result: Result[Any, PolluxError] = await handler.handle(current)
                duration = perf_counter() - start
            stage_durations[last_stage_name] = duration

            # Guard: handlers must return Success|Failure
            if not isinstance(result, Success | Failure):
                ctx.count("pipeline.invariant_violation", stage=last_stage_name)
                raise InvariantViolationError(
                    "Handler returned a non-Result value; expected Success|Failure.",
                    stage_name=last_stage_name,
                )

            if isinstance(result, Failure):
                # Increment operational counter, then raise with true stage identity
                ctx.count("pipeline.error", stage=last_stage_name)
                # Best-effort cleanup of ephemeral materialized files if any exist
                with contextlib.suppress(Exception):
                    self._cleanup_ephemeral_placeholders(current)
                raise PipelineError(str(result.error), last_stage_name, result.error)
            current = result.value

            # Attach telemetry durations to FinalizedCommand so ResultBuilder can surface metrics
            if isinstance(current, FinalizedCommand):
                # Avoid setdefault chaining to satisfy typing and be resilient to bad shapes
                existing = current.telemetry_data.get("durations")
                if isinstance(existing, dict):
                    existing.update(stage_durations)
                else:
                    current.telemetry_data["durations"] = dict(stage_durations)

        # Executor-level invariant: final value must be a ResultEnvelope-shaped dict.
        if not is_result_envelope(current):
            ctx.count(
                "pipeline.invariant_violation",
                stage=last_stage_name or "unknown_stage",
            )
            raise InvariantViolationError(
                "Executor ended without a ResultEnvelope; ensure the final stage produces the envelope (e.g., ResultBuilder).",
                stage_name=last_stage_name,
            )
        # Robustness fallback: if the terminal stage did not attach stage durations
        # (e.g., a custom terminal stage instead of ResultBuilder), surface the
        # executor-collected durations here without overwriting any existing data.
        try:
            metrics_obj = current.setdefault("metrics", {})
            if isinstance(metrics_obj, dict):
                existing = metrics_obj.get("durations")
                if isinstance(existing, dict):
                    for k, v in stage_durations.items():
                        existing.setdefault(k, v)
                else:
                    metrics_obj["durations"] = dict(stage_durations)
        except Exception as e:  # pragma: no cover - best-effort telemetry only
            # Never fail post-invariant; metrics are best-effort
            log.debug("Duration fallback attachment failed: %s", e, exc_info=True)
        return current

    def _cleanup_ephemeral_placeholders(self, obj: Any) -> None:
        """Unlink any ephemeral FilePlaceholder local files found in `obj`.

        Scans PlannedCommand/FinalizedCommand shapes and their plans/calls for
        FilePlaceholder entries with `ephemeral=True`. Errors are suppressed and
        never affect pipeline behavior.
        """
        try:

            def _scan_parts(parts: tuple[Any, ...] | list[Any]) -> None:
                for p in parts:
                    if isinstance(p, _ctypes.FilePlaceholder) and getattr(
                        p, "ephemeral", False
                    ):
                        with contextlib.suppress(Exception):
                            _Path(p.local_path).unlink()

            plan = None
            if isinstance(obj, _ctypes.PlannedCommand):
                plan = obj.execution_plan
            elif isinstance(obj, _ctypes.FinalizedCommand):
                plan = obj.planned.execution_plan

            if plan is None:
                return

            _scan_parts(plan.shared_parts)
            for c in plan.calls:
                if isinstance(c, _ctypes.APICall):
                    _scan_parts(c.api_parts)
        except Exception:
            # Never propagate cleanup issues
            return

    @property
    def stage_names(self) -> tuple[str, ...]:
        """Return the current pipeline's stage names in execution order."""
        return tuple(h.stage_name for h in self._exec_pipeline)

    @property
    def raw_pipeline(
        self,
    ) -> tuple[
        BaseAsyncHandler[Any, Any, PolluxError] | ErasedAsyncHandler,
        ...,
    ]:
        """Return the original handlers as constructed (read-only view).

        Useful for introspection and testing. This exposes either typed handlers
        or erased handlers, depending on how the executor was initialized.
        """
        return tuple(self._pipeline)


def create_executor(
    config: FrozenConfig | None = None,
    *,
    validate: bool | None = None,
) -> GeminiExecutor:
    """Create an executor with optional configuration.

    If no configuration is provided, it will be resolved from the environment
    using the new configuration system.

    Args:
        config: Optional configuration object (FrozenConfig or None).
        validate: Enable dev-time validation (overrides POLLUX_PIPELINE_VALIDATE). This does not affect the executor's final invariant, which always ensures a valid `ResultEnvelope`.

    Returns:
        An instance of GeminiExecutor.
    """
    # This is the only place where ambient configuration is resolved.
    # Use the new configuration system; explain=False returns FrozenConfig
    final_config = config if config is not None else resolve_config()

    return GeminiExecutor(final_config, validate=validate)
