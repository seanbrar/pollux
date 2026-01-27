"""Concurrency resolution helpers shared across frontdoor and pipeline.

Keeps a single source of truth for how client-side fan-out is bounded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pollux.config import FrozenConfig
    from pollux.core.execution_options import ExecutionOptions


def resolve_request_concurrency(
    *,
    n_calls: int,
    options: ExecutionOptions | None,
    cfg: FrozenConfig,
    rate_constrained: bool,
) -> int:
    """Resolve effective concurrency for vectorized execution.

    Priority:
    1) Force sequential (1) when rate constrained.
    2) Use explicit per-call `options.request_concurrency` when > 0.
    3) Use `cfg.request_concurrency` when > 0.
    4) Default to unbounded up to `n_calls`.
    """
    if n_calls <= 0:
        return 1
    if rate_constrained:
        return 1
    try:
        requested = int(getattr(options, "request_concurrency", 0) or 0)
    except Exception:
        requested = 0
    if requested > 0:
        return requested
    try:
        default_cfg = int(getattr(cfg, "request_concurrency", 0) or 0)
    except Exception:
        default_cfg = 0
    return default_cfg if default_cfg > 0 else n_calls
