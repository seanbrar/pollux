"""Provider contract characterization tests."""

from __future__ import annotations

import pytest

from pollux.errors import APIError, ContextOverflowError
from pollux.providers._errors import extract_retry_after_s, wrap_provider_error

pytestmark = pytest.mark.contract


# =============================================================================
# Provider Error Mapping (Contract)
# =============================================================================


def test_wrap_provider_error_extracts_status_and_retry_after_from_response_headers() -> (
    None
):
    """Provider SDK errors should map into APIError with structured retry metadata."""

    class _Resp:
        def __init__(self) -> None:
            self.status_code = 429
            self.headers = {"Retry-After": "2"}

    class _SdkError(Exception):
        def __init__(self) -> None:
            super().__init__("rate limited")
            self.response = _Resp()

    err = wrap_provider_error(
        _SdkError(),
        provider="openai",
        phase="generate",
        allow_network_errors=True,
        message="OpenAI generate failed",
    )

    assert isinstance(err, APIError)
    assert err.status_code == 429
    assert err.retry_after_s == 2.0
    assert err.retryable is True
    assert err.provider == "openai"
    assert err.phase == "generate"
    assert "429" in str(err)  # status code included in message


def test_wrap_provider_error_enriches_existing_api_error_without_clobbering() -> None:
    base = APIError("bad request", retryable=False, status_code=400)
    wrapped = wrap_provider_error(
        base,
        provider="gemini",
        phase="generate",
        allow_network_errors=True,
    )

    assert wrapped is base
    assert wrapped.status_code == 400
    assert wrapped.retryable is False
    assert wrapped.provider == "gemini"
    assert wrapped.phase == "generate"


def test_wrap_provider_error_returns_rate_limit_error_for_429() -> None:
    """429s should be catchable via RateLimitError (subclass of APIError)."""
    from pollux.errors import RateLimitError

    class _SdkError(Exception):
        def __init__(self) -> None:
            super().__init__("rate limited")
            self.status_code = 429

    err = wrap_provider_error(
        _SdkError(),
        provider="openai",
        phase="generate",
        allow_network_errors=True,
    )
    assert isinstance(err, RateLimitError)


def test_wrap_provider_error_returns_cache_error_for_cache_phase() -> None:
    """Cache failures should be catchable via CacheError (subclass of APIError)."""
    from pollux.errors import CacheError

    class _SdkError(Exception):
        def __init__(self) -> None:
            super().__init__("cache failed")
            self.status_code = 500

    err = wrap_provider_error(
        _SdkError(),
        provider="gemini",
        phase="cache",
        allow_network_errors=False,
    )
    assert isinstance(err, CacheError)


def test_wrap_provider_error_reraises_cancelled_error_without_active_exception() -> (
    None
):
    """Regression: CancelledError should be re-raised even without an active exception context."""
    import asyncio

    err = asyncio.CancelledError("cancelled")

    # This should raise CancelledError, NOT RuntimeError
    with pytest.raises(asyncio.CancelledError):
        wrap_provider_error(
            err,
            provider="test",
            phase="test",
            allow_network_errors=False,
        )


@pytest.mark.parametrize(
    ("retry_delay", "expected"),
    [
        ("8.352104981s", 8.352104981),
        ("8s", 8.0),
    ],
)
def test_extract_retry_after_from_google_retry_info_variants(
    retry_delay: str, expected: float
) -> None:
    """RetryInfo protobuf durations should parse consistently."""

    class _FakeError(Exception):
        def __init__(self) -> None:
            super().__init__("rate limited")
            self.details = {
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": retry_delay,
                        }
                    ]
                }
            }

    assert extract_retry_after_s(_FakeError()) == expected


def test_hint_for_400_with_api_key_message() -> None:
    """Gemini returns 400 (not 401/403) for invalid API keys; hint should fire."""

    class _SdkError(Exception):
        def __init__(self) -> None:
            super().__init__("API key not valid. Please pass a valid API key.")
            self.status_code = 400

    err = wrap_provider_error(
        _SdkError(),
        provider="gemini",
        phase="generate",
        allow_network_errors=True,
    )
    assert err.hint is not None
    assert "GEMINI_API_KEY" in err.hint


def test_wrap_provider_error_categorizes_rate_limit_error() -> None:
    class _SdkError(Exception):
        status_code: int

    # Status code 429
    err1 = wrap_provider_error(
        _SdkError("Too many requests"),
        provider="openai",
        phase="generate",
        allow_network_errors=True,
    )
    assert err1.error_category == "rate_limit"

    # Status code 429 from attribute
    exc = _SdkError("custom limit")
    exc.status_code = 429
    err2 = wrap_provider_error(
        exc,
        provider="openai",
        phase="generate",
        allow_network_errors=True,
    )
    assert err2.error_category == "rate_limit"


def test_wrap_provider_error_categorizes_auth_error() -> None:
    class AuthenticationError(Exception):
        pass

    err1 = wrap_provider_error(
        AuthenticationError("Invalid API key"),
        provider="openai",
        phase="generate",
        allow_network_errors=True,
    )
    assert err1.error_category == "auth_refreshable"

    class _SdkError(Exception):
        status_code: int

    exc = _SdkError("unauthorized access")
    exc.status_code = 401
    err2 = wrap_provider_error(
        exc,
        provider="anthropic",
        phase="generate",
        allow_network_errors=True,
    )
    assert err2.error_category == "auth_refreshable"


def test_wrap_provider_error_categorizes_capacity_error() -> None:
    class InternalServerError(Exception):
        pass

    err1 = wrap_provider_error(
        InternalServerError("Overloaded"),
        provider="openai",
        phase="generate",
        allow_network_errors=True,
    )
    assert err1.error_category == "capacity"

    class _SdkError(Exception):
        status_code: int

    exc = _SdkError("service unavailable")
    exc.status_code = 503
    err2 = wrap_provider_error(
        exc,
        provider="openai",
        phase="generate",
        allow_network_errors=True,
    )
    assert err2.error_category == "capacity"


def test_wrap_provider_error_categorizes_context_overflow_error() -> None:
    class BadRequestError(Exception):
        pass

    err1 = wrap_provider_error(
        BadRequestError("This model's maximum context length is 8192 tokens"),
        provider="openai",
        phase="generate",
        allow_network_errors=True,
    )
    assert err1.error_category == "context_overflow"

    class _SdkError(Exception):
        status_code: int

    exc = _SdkError("Prompt exceeds maximum context length")
    exc.status_code = 400
    err2 = wrap_provider_error(
        exc,
        provider="anthropic",
        phase="generate",
        allow_network_errors=True,
    )
    assert err2.error_category == "context_overflow"


def test_wrap_provider_error_returns_context_overflow_with_token_counts() -> None:
    class BadRequestError(Exception):
        pass

    err = wrap_provider_error(
        BadRequestError(
            "Requested 12,345 tokens, maximum context length allowed is 8,192"
        ),
        provider="local",
        phase="generate",
        allow_network_errors=True,
    )

    assert isinstance(err, ContextOverflowError)
    assert err.error_category == "context_overflow"
    assert err.n_tokens == 12345
    assert err.n_ctx == 8192
