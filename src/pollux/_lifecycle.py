"""Shared asynchronous resource-lifecycle helpers."""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any
from weakref import WeakSet

logger = logging.getLogger(__name__)
_closed_iterators: WeakSet[Any] = WeakSet()


async def close_async_iterator(iterator: Any) -> None:
    """Close an async iterator without masking an interaction's primary error."""
    close = getattr(iterator, "aclose", None)
    if not callable(close):
        close = getattr(iterator, "close", None)
    if not callable(close):
        return
    try:
        if iterator in _closed_iterators:
            return
        _closed_iterators.add(iterator)
    except TypeError:
        # Some third-party stream wrappers cannot be weak-referenced. Prefer a
        # private marker when they allow attributes; otherwise rely on the SDK's
        # idempotent close contract.
        try:
            if getattr(iterator, "_pollux_closed", False):
                return
            iterator._pollux_closed = True
        except (AttributeError, TypeError):
            pass
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Async iterator cleanup failed: %s", exc)
