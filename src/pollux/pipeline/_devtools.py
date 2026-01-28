"""Developer utilities for advanced pipeline composition (internal).

This module exposes helpers that are useful when authoring extensions or
composing custom pipelines. It is not part of the stable public API and may
change between minor versions.
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any

from pollux._dev_flags import dev_validate_enabled
from pollux.core.exceptions import InvariantViolationError
from pollux.core.types import (
    explain_invalid_result_envelope,
    is_result_envelope,
)
from pollux.pipeline._erasure import is_erased_handler

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pollux.core.exceptions import PolluxError

    from ._erasure import ErasedAsyncHandler
    from .base import BaseAsyncHandler

log = logging.getLogger(__name__)


def compose_pipeline(
    *handlers: BaseAsyncHandler[Any, Any, PolluxError] | ErasedAsyncHandler,
    strict: bool = True,
) -> list[BaseAsyncHandler[Any, Any, PolluxError] | ErasedAsyncHandler]:
    """Validate and return a typed handler sequence for executor use.

    - Confirms each handler has an async ``handle``.
    - Ensures the final stage is an envelope builder when detectable (by
      `_produces_envelope`) and `strict=True`. For erased handlers we defer
      to the executor's final invariant.
    - Optionally performs extra debug checks when POLLUX_PIPELINE_VALIDATE=1.
    """
    if not handlers:
        raise ValueError("compose_pipeline() requires at least one handler")

    for h in handlers:
        fn = getattr(h, "handle", None)
        if not callable(fn) or not inspect.iscoroutinefunction(fn):
            raise TypeError(
                f"Handler {type(h).__name__} must define an async 'handle' method"
            )

    last = handlers[-1]
    if strict:
        # Enforce explicit terminal-stage marker for non-erased handlers.
        if not is_erased_handler(last):
            marker = getattr(last, "_produces_envelope", None)
            if marker is not True:
                raise TypeError(
                    "The final handler must produce a ResultEnvelope (e.g., ResultBuilder). "
                    "Mark custom terminal stages with '_produces_envelope = True'."
                )
    else:  # strict == False
        # Advisory for extension authors: when strict checks are disabled or marker
        # is not detectable, the executor's final invariant will enforce shape.
        marker = getattr(last, "_produces_envelope", None)
        if marker is None or bool(marker) is not True:
            last_name = type(last).__name__
            log.debug(
                "compose_pipeline(strict=False): final handler %s marker not enforced; "
                "executor invariant will validate envelope shape at runtime.",
                last_name,
            )

    if dev_validate_enabled():
        # Debug-only: soft checks for annotations to help extension authors
        for h in handlers:
            try:
                hints = h.handle.__annotations__
                if not hints:
                    log.warning("Handler %s lacks type annotations", type(h).__name__)
                    continue
                if "return" not in hints:
                    log.warning(
                        "Handler %s.handle missing return annotation", type(h).__name__
                    )
            except Exception as e:  # pragma: no cover - advisory only
                log.debug("Pipeline validate hints failed for %s: %s", h, e)

    return list(handlers)


def validate_result_envelope(result: object, *, stage_name: str | None = None) -> None:
    """Dev-only structural validator for `ResultEnvelope` with richer errors.

    Raises an `InvariantViolationError` with a precise reason when the
    structure is invalid. This is intended for development flows; the
    executor always enforces a final invariant in production.
    """
    # Fast happy path using centralized predicate
    if is_result_envelope(result):
        # Optional, very slim validation of high-value internals for extensions
        _validate_envelope_metrics(result)  # best-effort, dev-only
        _validate_envelope_optionals(result)  # diagnostics/validation_warnings
        # Minimal confidence range check for custom terminal stages
        try:
            conf = getattr(result, "get", lambda _k, _d=None: None)("confidence")
            if isinstance(conf, int | float) and not (0.0 <= float(conf) <= 1.0):
                raise InvariantViolationError("confidence must be in [0.0, 1.0]")
        except InvariantViolationError:
            raise
        except Exception as e:
            # Advisory only; avoid raising for unexpected shapes
            log.debug("Confidence dev-validation advisory: %s", e)
        return
    # Produce a concise reason via shared helper
    reason = explain_invalid_result_envelope(result)
    raise InvariantViolationError(
        reason or "Stage did not produce a valid ResultEnvelope; check field shapes.",
        stage_name=stage_name,
    )


def _validate_envelope_metrics(result: Mapping[str, Any]) -> None:
    """Slim, high-utility checks for inner metrics/usage shapes (dev-only).

    Goals: catch common extension mistakes without adding runtime overhead.
    - metrics.durations: dict[str, int|float]
    - metrics.hints: dict[str, bool] (when present)
    - usage: dict[str, Any] (already shape-checked at top level)
    Raises `InvariantViolationError` with a concise reason on violation.
    """
    try:
        metrics = result.get("metrics")
        if isinstance(metrics, dict):
            durations = metrics.get("durations")
            if durations is not None:
                if not isinstance(durations, dict):
                    raise InvariantViolationError("metrics.durations must be a dict")
                for k, v in durations.items():
                    if not isinstance(k, str):
                        raise InvariantViolationError(
                            "metrics.durations keys must be str"
                        )
                    if not isinstance(v, int | float):
                        raise InvariantViolationError(
                            "metrics.durations values must be int|float"
                        )
            hints = metrics.get("hints")
            if hints is not None:
                if not isinstance(hints, dict):
                    raise InvariantViolationError("metrics.hints must be a dict")
                for hk, hv in hints.items():
                    if not isinstance(hk, str):
                        raise InvariantViolationError("metrics.hints keys must be str")
                    if not isinstance(hv, bool):
                        raise InvariantViolationError(
                            "metrics.hints values must be bool"
                        )
    except InvariantViolationError:
        raise
    except Exception as e:
        # Dev-only advisory log; avoid raising for unexpected issues
        log.debug("Envelope metrics dev-validation advisory: %s", e)


def _validate_envelope_optionals(result: Mapping[str, Any]) -> None:
    """Dev-only checks for optional envelope fields with common mistakes.

    - diagnostics: dict when present
    - validation_warnings: tuple[str, ...] when present

    Raises `InvariantViolationError` with a concise reason on violation.
    """
    try:
        diagnostics = result.get("diagnostics")
        if diagnostics is not None and not isinstance(diagnostics, dict):
            raise InvariantViolationError("diagnostics must be a dict when present")

        warnings = result.get("validation_warnings")
        if warnings is not None:
            if not isinstance(warnings, tuple):
                raise InvariantViolationError(
                    "validation_warnings must be a tuple[str, ...] when present"
                )
            for w in warnings:
                if not isinstance(w, str):
                    raise InvariantViolationError(
                        "validation_warnings elements must be str"
                    )
    except InvariantViolationError:
        raise
    except Exception as e:  # pragma: no cover - advisory only
        log.debug("Envelope optionals dev-validation advisory: %s", e)


__all__ = ("compose_pipeline", "validate_result_envelope")
