"""Shared provider-side error helpers.

Providers should attach retry metadata via APIError so core retry logic can be
bounded and deterministic without brittle substring matching.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from pollux._http import RETRYABLE_STATUS_CODES
from pollux.errors import (
    APIError,
    CacheError,
    RateLimitError,
    _walk_exception_chain,
)


def extract_status_code(exc: BaseException) -> int | None:
    """Walk the exception chain to find an HTTP status code."""
    for e in _walk_exception_chain(exc):
        for attr in ("status_code", "status"):
            value = getattr(e, attr, None)
            if isinstance(value, int) and 100 <= value <= 599:
                return value
        response = getattr(e, "response", None)
        value = getattr(response, "status_code", None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    return None


_PROTO_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)s$")


def _extract_retry_info_seconds(exc: BaseException) -> float | None:
    """Extract retry delay from Google API-style RetryInfo in error details.

    Gemini SDK ``ClientError`` exposes the parsed JSON body via a ``.details``
    attribute shaped like::

        {"error": {"details": [{"@type": "...RetryInfo", "retryDelay": "8s"}]}}

    The ``retryDelay`` value is a protobuf Duration string (e.g. ``"8s"``,
    ``"8.352104981s"``).
    """
    details: Any = getattr(exc, "details", None)
    if not isinstance(details, dict):
        return None
    error: Any = details.get("error")
    if not isinstance(error, dict):
        return None
    detail_list: Any = error.get("details")
    if not isinstance(detail_list, list):
        return None
    for entry in detail_list:
        if not isinstance(entry, dict):
            continue
        at_type = entry.get("@type", "")
        if not isinstance(at_type, str) or "RetryInfo" not in at_type:
            continue
        delay_raw = entry.get("retryDelay")
        if not isinstance(delay_raw, str):
            continue
        m = _PROTO_DURATION_RE.match(delay_raw)
        if m:
            return float(m.group(1))
    return None


def extract_retry_after_s(exc: BaseException) -> float | None:
    """Walk the exception chain to find a retry-after delay in seconds."""
    for e in _walk_exception_chain(exc):
        value = getattr(e, "retry_after", None)
        if isinstance(value, (int, float)) and value >= 0:
            return float(value)

        response = getattr(e, "response", None)
        headers: Any = getattr(response, "headers", None)
        if headers is not None:
            raw: Any = None
            try:
                raw = headers.get("Retry-After")
            except Exception:
                raw = None
            if isinstance(raw, str) and raw.strip():
                seconds: float | None
                try:
                    seconds = float(raw)
                except Exception:
                    seconds = None
                if seconds is not None and seconds >= 0:
                    return seconds

        # Fallback: Google API-style RetryInfo in error details.
        retry_info = _extract_retry_info_seconds(e)
        if retry_info is not None:
            return retry_info
    return None


def _auth_hint(
    provider: str, status_code: int | None, cause_message: str
) -> str | None:
    """Generate a hint for auth errors where naming the env var is useful."""
    cause_lower = cause_message.lower()
    if status_code in {401, 403} or (
        status_code == 400 and ("api key" in cause_lower or "api_key" in cause_lower)
    ):
        env_var = "API key"
        if provider == "openai":
            env_var = "OPENAI_API_KEY"
        elif provider == "gemini":
            env_var = "GEMINI_API_KEY"
        return (
            f"Check credentials/permissions (try setting {env_var} or Config.api_key)."
        )
    return None


def wrap_provider_error(
    exc: BaseException,
    *,
    provider: str,
    phase: str,
    allow_network_errors: bool,
    message: str | None = None,
    hint: str | None = None,
) -> APIError:
    """Map provider SDK exceptions into APIError with stable retry metadata."""
    if isinstance(exc, asyncio.CancelledError):
        raise exc

    # Already wrapped — fill in missing context only.
    if isinstance(exc, APIError):
        if exc.provider is None:
            exc.provider = provider
        if exc.phase is None:
            exc.phase = phase
        if hint is not None and exc.hint is None:
            exc.hint = hint
        return exc

    status_code = extract_status_code(exc)
    retry_after_s = extract_retry_after_s(exc)

    retryable = retry_after_s is not None
    if isinstance(status_code, int) and status_code in RETRYABLE_STATUS_CODES:
        retryable = True
    elif allow_network_errors:
        for e in _walk_exception_chain(exc):
            if isinstance(e, (httpx.TimeoutException, httpx.RequestError)):
                retryable = True
                break

    derived_hint = (
        hint
        if hint is not None
        else _auth_hint(
            provider,
            status_code,
            str(exc),
        )
    )

    msg = message or f"{provider} {phase} failed"

    err_cls: type[APIError] = APIError
    if status_code == 429:
        err_cls = RateLimitError
    elif phase == "cache":
        err_cls = CacheError

    status_note = f" (status={status_code})" if isinstance(status_code, int) else ""
    cause = str(exc)
    return err_cls(
        f"{msg}{status_note}: {cause}" if cause else f"{msg}{status_note}",
        hint=derived_hint,
        retryable=retryable,
        status_code=status_code,
        retry_after_s=retry_after_s,
        provider=provider,
        phase=phase,
    )
