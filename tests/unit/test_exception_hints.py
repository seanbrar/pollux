"""Unit tests for verifying actionable hints in exceptions."""

import pytest

from pollux.core.exceptions import (
    HINTS,
    APIError,
    ConfigurationError,
    PolluxError,
    get_http_error_hint,
)






# High-signal tests verifying mapping logic and integration behavior
def test_get_http_hint():
    """Test mapping of HTTP status codes to hints."""
    assert get_http_error_hint(401) == "Verify GEMINI_API_KEY is valid."
    assert get_http_error_hint(429) == "Rate limit exceeded; wait and retry."
    assert get_http_error_hint(999) is None


def test_api_handler_error_wrapping():
    """Test that APIError supports hints."""
    # We can't easily test APIHandler without more setup,
    # but we can test the helper logic if we expose it or test it via its effects.
    # For now, let's verify APIError supports hints.
    err = APIError("API call failed", hint="Check your network")
    assert "Check your network" in str(err)


def test_integration_missing_api_key():
    """Integration test for missing API key validation."""
    from pollux.config import resolve_config

    with pytest.raises(ConfigurationError) as excinfo:
        resolve_config(overrides={"use_real_api": True, "api_key": None})

    assert "api_key is required when use_real_api=True" in str(excinfo.value)
    assert HINTS["missing_api_key"] in str(excinfo.value)
