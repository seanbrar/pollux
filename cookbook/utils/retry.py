"""Simple async retry helper for flaky provider/network conditions.

Designed for use in cookbook recipes without touching core library code.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

T = TypeVar("T")

DEFAULT_SUBSTRINGS: tuple[str, ...] = (
    "Connection reset",
    "ECONNRESET",
    "temporarily unavailable",
    "deadline exceeded",
    "rate limit",
    "429",
    "not in ACTIVE state",
    "not in an ACTIVE state",
    "processing state",
)


async def retry_async(
    factory: Callable[[], Awaitable[T]],
    *,
    retries: int = 3,
    initial_delay: float = 1.0,
    backoff: float = 2.0,
    retry_on: Iterable[str] | None = None,
) -> T:
    """Run an async operation with basic exponential backoff on select errors.

    Args:
        factory: Zero-arg coroutine factory so the call is recreated on retry.
        retries: Number of additional attempts after the first try.
        initial_delay: Initial sleep in seconds before the first retry.
        backoff: Multiplier for subsequent delays.
        retry_on: Substrings that, when present in the exception text, trigger a retry.
    """
    attempts = retries + 1
    delay = max(0.0, float(initial_delay))
    substrings = tuple(retry_on) if retry_on is not None else DEFAULT_SUBSTRINGS
    last_exc: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await factory()
        except Exception as e:
            msg = str(e)
            last_exc = e
            if (
                not any(s.lower() in msg.lower() for s in substrings)
                or attempt >= attempts
            ):
                raise
            await asyncio.sleep(delay)
            delay *= backoff if backoff > 0 else 1.0
    # Should not reach here; raise the last exception as a safeguard
    assert last_exc is not None
    raise last_exc
