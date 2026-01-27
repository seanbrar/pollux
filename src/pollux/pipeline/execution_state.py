"""Execution-time internal state helpers for the pipeline.

These types are used only within pipeline handlers to pass small, explicit
execution hints between components without relying on magic config keys.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionHints:
    """Small, explicit hints for execution-time adapters.

    Adapters may choose to read these hints to adjust behavior. Handlers must
    remain correct when hints are absent.
    """

    cached_content: str | None = None
