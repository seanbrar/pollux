"""Internal type-erasure utilities for pipeline handlers.

These helpers allow the executor to store a heterogeneous list of handlers
while keeping a small, simple public API surface for extension authors.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Protocol, TypeGuard, TypeVar, cast

from pollux.core.exceptions import PolluxError

if TYPE_CHECKING:
    from pollux.core.types import Result

    from .base import BaseAsyncHandler

T_In = TypeVar("T_In", contravariant=True)
T_Out = TypeVar("T_Out")
T_Error = TypeVar("T_Error", bound=PolluxError)


class ErasedAsyncHandler(Protocol):
    """Type-erased async handler for heterogeneous pipeline storage (internal)."""

    stage_name: str

    async def handle(self, command: Any) -> Result[Any, PolluxError]: ...


def is_erased_handler(obj: object) -> TypeGuard[ErasedAsyncHandler]:
    """Return True if object is a type-erased handler (internal guard).

    We require a sentinel attribute set by our wrapper to avoid falsely
    classifying typed handlers that happen to define a ``stage_name``.
    """
    try:
        if getattr(obj, "__erased__", False) is not True:
            return False
        handle = getattr(obj, "handle", None)
        stage_name = getattr(obj, "stage_name", None)
        return isinstance(stage_name, str) and inspect.iscoroutinefunction(handle)
    except Exception:
        return False


class _ErasedWrapper[T_In, T_Out, T_Error: PolluxError]:
    """Adapter from ``BaseAsyncHandler`` to ``ErasedAsyncHandler`` (internal)."""

    def __init__(self, inner: BaseAsyncHandler[T_In, T_Out, T_Error]):
        self._inner = inner
        self.stage_name = inner.__class__.__name__
        # Sentinel used to positively identify erased instances
        self.__erased__ = True

    async def handle(self, command: Any) -> Result[Any, PolluxError]:
        _res = await self._inner.handle(cast("T_In", command))
        return cast("Result[Any, PolluxError]", _res)


def erase[T_In, T_Out, T_Error: PolluxError](
    handler: BaseAsyncHandler[T_In, T_Out, T_Error] | ErasedAsyncHandler,
) -> ErasedAsyncHandler:
    """Erase a typed handler to a uniform executor-compatible wrapper (internal)."""
    maybe_handle = getattr(handler, "handle", None)
    if not callable(maybe_handle):
        raise TypeError(
            "erase() expects a BaseAsyncHandler-like object with an async 'handle' method"
        )
    if not inspect.iscoroutinefunction(maybe_handle):
        raise TypeError(
            "erase() requires 'handle' to be defined as an async coroutine function"
        )
    # If already erased by our wrapper (sentinel present), return as-is
    if getattr(handler, "__erased__", False) is True:
        return cast("ErasedAsyncHandler", handler)
    return cast("ErasedAsyncHandler", _ErasedWrapper(handler))


__all__ = ()  # internal-only
