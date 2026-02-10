"""Async single-flight helper.

Used to coordinate concurrent requests for the same key so only one coroutine
performs the work, while others await the same Future.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

K = TypeVar("K")
T = TypeVar("T")


def consume_future_exception(fut: asyncio.Future[Any]) -> None:
    """Avoid 'Future exception was never retrieved' for coordination futures."""
    try:
        _ = fut.exception()
    except asyncio.CancelledError:
        return


async def singleflight_cached(
    key: K,
    *,
    lock: asyncio.Lock,
    inflight: dict[K, asyncio.Future[T]],
    cache_get: Callable[[K], T | None],
    cache_set: Callable[[K, T], None],
    work: Callable[[], Awaitable[T]],
) -> T:
    """Return cached value for key, or compute it once with single-flight.

    - If cached, returns immediately.
    - If inflight, awaits the existing Future.
    - Otherwise, creates a Future and runs *work* as the single creator.
    """
    cached = cache_get(key)
    if cached is not None:
        return cached

    async with lock:
        cached = cache_get(key)
        if cached is not None:
            return cached

        fut = inflight.get(key)
        if fut is None:
            fut = asyncio.get_running_loop().create_future()
            fut.add_done_callback(consume_future_exception)
            inflight[key] = fut
            creator = True
        else:
            creator = False

    if not creator:
        return await fut

    try:
        value = await work()
    except asyncio.CancelledError:
        fut.cancel()
        raise
    except Exception as e:
        fut.set_exception(e)
        raise
    else:
        async with lock:
            cache_set(key, value)
        fut.set_result(value)
        return value
    finally:
        async with lock:
            inflight.pop(key, None)
