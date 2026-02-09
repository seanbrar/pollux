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

from pollux.errors import APIError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

T = TypeVar("T")

_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 409, 429, 500, 502, 503, 504})


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


def _walk_exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield exc and its causes/contexts, with cycle protection."""
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        cur = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        yield cur

        cause = cur.__cause__
        if isinstance(cause, BaseException):
            stack.append(cause)
        context = cur.__context__
        if isinstance(context, BaseException):
            stack.append(context)


def _is_transient_network_error(exc: BaseException) -> bool:
    # Core retry should be robust even if provider SDKs wrap underlying errors.
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
            # RequestError is a stable base class for transport-level failures.
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
    - APIError is retried only when provider marks it retryable or includes a
      known retryable HTTP status code.
    - A small set of timeout exceptions are retried as a pragmatic fallback.
    """
    if isinstance(exc, asyncio.CancelledError):
        return False

    if isinstance(exc, APIError):
        return (exc.retryable is True) or (
            isinstance(exc.status_code, int)
            and exc.status_code in _RETRYABLE_STATUS_CODES
        )

    return _is_transient_network_error(exc)


def should_retry_side_effect(exc: BaseException) -> bool:
    """Return True when a side-effectful operation should be retried.

    Side effects (uploads, cache creation) can create duplicate artifacts on
    ambiguous failures. To minimize surprise, retries are only attempted when
    we have explicit provider signals (HTTP status codes / Retry-After).
    """
    if isinstance(exc, asyncio.CancelledError):
        return False

    if isinstance(exc, APIError):
        if _retry_after_from_error(exc) is not None:
            return True
        return (
            isinstance(exc.status_code, int)
            and exc.status_code in _RETRYABLE_STATUS_CODES
        )

    # Never retry unknown/raw exceptions for side effects by default.
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
