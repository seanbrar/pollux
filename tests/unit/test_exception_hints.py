"""Unit tests for verifying actionable hints in exceptions."""

import pytest

from pollux.core.exceptions import (
    HINTS,
    APIError,
    ConfigurationError,
    GeminiBatchError,
    get_http_error_hint,
)


def test_gemini_batch_error_with_hint():
    """Test that GeminiBatchError correctly includes a hint in the message."""
    message = "Something went wrong"
    hint = "Try turning it off and on again"
    err = GeminiBatchError(message, hint=hint)
    assert str(err) == f"{message}. {hint}"
    assert err.hint == hint


def test_gemini_batch_error_without_hint():
    """Test that GeminiBatchError works without a hint."""
    message = "Something went wrong"
    err = GeminiBatchError(message)
    assert str(err) == message
    assert err.hint is None


def test_configuration_error_with_standard_hint():
    """Test ConfigurationError with a predefined hint."""
    message = "Config failed"
    hint = HINTS["missing_api_key"]
    err = ConfigurationError(message, hint=hint)
    assert str(err) == f"{message}. {hint}"
    assert hint in str(err)


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
