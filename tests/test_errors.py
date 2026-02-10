from __future__ import annotations

import pytest

from pollux.errors import APIError, CacheError, PolluxError, RateLimitError

pytestmark = pytest.mark.unit


def test_api_error_structured_metadata() -> None:
    err = APIError(
        "boom",
        hint="do this",
        retryable=True,
        status_code=429,
        retry_after_s=2.0,
        provider="gemini",
        phase="generate",
        call_idx=1,
    )

    assert str(err) == "boom"
    assert err.hint == "do this"
    assert err.retryable is True
    assert err.status_code == 429
    assert err.retry_after_s == 2.0
    assert err.provider == "gemini"
    assert err.phase == "generate"
    assert err.call_idx == 1


def test_api_error_defaults_to_none() -> None:
    err = APIError("fail")
    assert err.hint is None
    assert err.retryable is None
    assert err.status_code is None
    assert err.retry_after_s is None
    assert err.provider is None
    assert err.phase is None
    assert err.call_idx is None


def test_subclass_hierarchy() -> None:
    """CacheError and RateLimitError are catchable as APIError and PolluxError."""
    cache_err = CacheError("cache fail", phase="cache", provider="gemini")
    rate_err = RateLimitError("rate limit", status_code=429, retryable=True)

    assert isinstance(cache_err, APIError)
    assert isinstance(cache_err, PolluxError)
    assert isinstance(rate_err, APIError)
    assert isinstance(rate_err, PolluxError)
