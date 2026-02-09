"""Shared provider-side error helpers.

Providers should attach retry metadata via APIError so core retry logic can be
bounded and deterministic without brittle substring matching.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from pollux.errors import APIError

if TYPE_CHECKING:
    from collections.abc import Iterator

_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 409, 429, 500, 502, 503, 504})


def _walk_exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield exc and its causes/contexts (both branches), with cycle protection."""
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


def extract_status_code(exc: BaseException) -> int | None:
    for e in _walk_exception_chain(exc):
        for attr in ("status_code", "status"):
            value = getattr(e, attr, None)
            if isinstance(value, int):
                return value
        response = getattr(e, "response", None)
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None


def extract_retry_after_s(exc: BaseException) -> float | None:
    for e in _walk_exception_chain(exc):
        value = getattr(e, "retry_after", None)
        if isinstance(value, (int, float)) and value >= 0:
            return float(value)

        response = getattr(e, "response", None)
        headers: Any = getattr(response, "headers", None)
        if headers is None:
            continue
        raw: Any = None
        try:
            raw = headers.get("Retry-After")
        except Exception:
            raw = None
        if not isinstance(raw, str) or not raw.strip():
            continue
        seconds: float | None
        try:
            seconds = float(raw)
        except Exception:
            seconds = None
        if seconds is None:
            continue
        if seconds >= 0:
            return seconds
    return None


def wrap_transient_api_error(
    prefix: str,
    exc: BaseException,
    *,
    allow_network_errors: bool,
) -> APIError:
    """Wrap unknown provider exceptions into APIError with retry metadata."""
    if isinstance(exc, APIError):
        return exc

    status_code = extract_status_code(exc)
    retry_after_s = extract_retry_after_s(exc)

    retryable = False
    if isinstance(status_code, int) and status_code in _RETRYABLE_STATUS_CODES:
        retryable = True
    elif allow_network_errors:
        for e in _walk_exception_chain(exc):
            # RequestError is a stable base class for transport-level failures.
            if isinstance(e, (httpx.TimeoutException, httpx.RequestError)):
                retryable = True
                break

    return APIError(
        f"{prefix}: {exc}",
        retryable=retryable,
        status_code=status_code,
        retry_after_s=retry_after_s,
    )
