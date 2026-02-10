"""Minimal async retry with explicit error contracts.

Design goals:
- Small API surface (MTMT-friendly)
- Explicit state (policy + attempt counters)
- No brittle substring matching for retry decisions
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import random
import time
from typing import TYPE_CHECKING, TypeVar

from pollux.errors import APIError, _walk_exception_chain

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry policy with exponential backoff and optional jitter."""

    # Defaults are intentionally conservative: retries should help without
    # surprising tail-latency.
    max_attempts: int = 2
    initial_delay_s: float = 0.5
    backoff_multiplier: float = 2.0
    max_delay_s: float = 5.0
    jitter: bool = True  # "full jitter" when enabled
    max_elapsed_s: float | None = 15.0

    def __post_init__(self) -> None:
        """Validate invariants to keep retry behavior predictable."""
        if self.max_attempts < 1:
            raise ValueError("RetryPolicy.max_attempts must be >= 1")
        if self.initial_delay_s < 0:
            raise ValueError("RetryPolicy.initial_delay_s must be >= 0")
        if self.backoff_multiplier <= 0:
            raise ValueError("RetryPolicy.backoff_multiplier must be > 0")
        if self.max_delay_s < 0:
            raise ValueError("RetryPolicy.max_delay_s must be >= 0")
        if self.max_elapsed_s is not None and self.max_elapsed_s < 0:
            raise ValueError("RetryPolicy.max_elapsed_s must be >= 0 or None")


def _retry_after_from_error(exc: BaseException) -> float | None:
    if isinstance(exc, APIError):
        v = exc.retry_after_s
        if isinstance(v, (int, float)) and v >= 0:
            return float(v)
    return None


def _is_transient_network_error(exc: BaseException) -> bool:
    """Pragmatic fallback for unwrapped network errors reaching retry."""
    httpx = None
    try:
        import httpx as _httpx

        httpx = _httpx
    except Exception:
        httpx = None

    for e in _walk_exception_chain(exc):
        if isinstance(e, (TimeoutError, asyncio.TimeoutError)):
            return True
        if httpx is not None:
            request_error = getattr(httpx, "RequestError", None)
            timeout_exc = getattr(httpx, "TimeoutException", None)
            if isinstance(timeout_exc, type) and isinstance(e, timeout_exc):
                return True
            if isinstance(request_error, type) and isinstance(e, request_error):
                return True
    return False


def should_retry_generate(exc: BaseException) -> bool:
    """Return True when a *generate* exception should be retried.

    Contract:
    - Cancellation is never retried.
    - APIError is retried when the provider marked it retryable.
    - Unwrapped transient network errors are retried as a pragmatic fallback.
    """
    if isinstance(exc, asyncio.CancelledError):
        return False

    if isinstance(exc, APIError):
        return exc.retryable is True

    return _is_transient_network_error(exc)


def should_retry_side_effect(exc: BaseException) -> bool:
    """Return True when a side-effectful operation should be retried.

    Side effects (uploads, cache creation) can create duplicate artifacts on
    ambiguous failures. Retries require explicit provider signal (retryable=True
    is only set for HTTP status codes / Retry-After, not network errors, when
    allow_network_errors=False).
    """
    if isinstance(exc, asyncio.CancelledError):
        return False

    if isinstance(exc, APIError):
        return exc.retryable is True

    return False


# Backwards-compatible internal alias.
should_retry = should_retry_generate


def _compute_backoff_delay(policy: RetryPolicy, *, retry_index: int) -> float:
    # retry_index starts at 1 for the first retry sleep.
    base = policy.initial_delay_s * (
        policy.backoff_multiplier ** max(0, retry_index - 1)
    )
    base = min(policy.max_delay_s, base)
    if base <= 0:
        return 0.0
    if not policy.jitter:
        return base
    # Full jitter: random in [0, base] to avoid thundering herd.
    return random.random() * base  # noqa: S311


async def retry_async(
    factory: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    should_retry: Callable[[BaseException], bool] = should_retry_generate,
) -> T:
    """Run an async factory with bounded retries."""
    start = time.monotonic()
    last_exc: BaseException | None = None

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await factory()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_exc = exc
            if not should_retry(exc) or attempt >= policy.max_attempts:
                raise

            retry_after = _retry_after_from_error(exc)
            delay = _compute_backoff_delay(policy, retry_index=attempt)
            if retry_after is not None:
                delay = max(delay, retry_after)

            if policy.max_elapsed_s is not None:
                remaining = policy.max_elapsed_s - (time.monotonic() - start)
                if remaining <= 0:
                    raise
                delay = min(delay, remaining)

            if delay > 0:
                await asyncio.sleep(delay)

    # Defensive: loop should always return or raise.
    if last_exc is None:  # pragma: no cover
        raise RuntimeError("retry_async exhausted without an exception")
    raise last_exc
