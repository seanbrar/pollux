"""Internal helpers for development-time feature flags.

This module intentionally stays minimal to preserve simplicity and avoid
cross-module coupling. It centralizes how we check opt-in validation toggles
so semantics remain consistent across the codebase.
"""

from __future__ import annotations

import os

__all__ = ["dev_raw_preview_enabled", "dev_validate_enabled"]


def dev_validate_enabled(*, override: bool | None = None) -> bool:
    """Return True when dev-time validation is enabled.

    - If ``override`` is provided, it takes precedence.
    - Otherwise, returns True when the environment variable
      ``POLLUX_PIPELINE_VALIDATE`` is exactly ``"1"``.
    """
    if override is not None:
        return bool(override)
    return os.getenv("POLLUX_PIPELINE_VALIDATE") == "1"


def dev_raw_preview_enabled(*, override: bool | None = None) -> bool:
    """Return True when attaching raw preview debug data is enabled.

    Semantics:
    - If ``override`` is provided, it takes precedence.
    - Otherwise, returns True when the environment variable
      ``POLLUX_TELEMETRY_RAW_PREVIEW`` is exactly ``"1"``.

    Notes:
    - Kept independent from ``POLLUX_TELEMETRY`` to allow researchers to
      enable previews without enabling full telemetry collection.
    - This helper centralizes env handling to keep hot paths import-fast and
      to simplify tests.
    """
    if override is not None:
        return bool(override)
    return os.getenv("POLLUX_TELEMETRY_RAW_PREVIEW") == "1"
