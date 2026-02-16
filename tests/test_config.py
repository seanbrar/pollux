"""Configuration boundary tests for the simplified v1 API."""

from __future__ import annotations

import pytest

from pollux.config import Config
from pollux.errors import ConfigurationError

pytestmark = pytest.mark.unit


def test_config_creation_with_mock_mode(gemini_model: str) -> None:
    """Config can be created with mock mode (no API key needed)."""
    cfg = Config(provider="gemini", model=gemini_model, use_mock=True)
    assert cfg.provider == "gemini"
    assert cfg.model == gemini_model


def test_config_auto_resolves_api_key_from_env(
    monkeypatch: pytest.MonkeyPatch,
    gemini_model: str,
) -> None:
    """API key should be auto-resolved from environment."""
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    cfg = Config(provider="gemini", model=gemini_model)

    assert cfg.api_key == "env-key"


def test_explicit_api_key_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
    gemini_model: str,
) -> None:
    """Explicit api_key should override env."""
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")

    cfg = Config(provider="gemini", model=gemini_model, api_key="explicit-key")

    assert cfg.api_key == "explicit-key"


def test_openai_provider_uses_openai_api_key(
    monkeypatch: pytest.MonkeyPatch,
    openai_model: str,
) -> None:
    """Provider-specific env key selection should prefer OPENAI_API_KEY."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    cfg = Config(provider="openai", model=openai_model)

    assert cfg.provider == "openai"
    assert cfg.api_key == "openai-secret"


def test_missing_api_key_raises_clear_error(
    monkeypatch: pytest.MonkeyPatch,
    gemini_model: str,
) -> None:
    """Missing API key without mock mode must fail clearly."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="API key required") as exc:
        Config(provider="gemini", model=gemini_model)
    assert exc.value.hint is not None
    assert "GEMINI_API_KEY" in exc.value.hint


def test_mock_mode_does_not_require_api_key(
    monkeypatch: pytest.MonkeyPatch,
    gemini_model: str,
) -> None:
    """Mock mode should work without an API key."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    cfg = Config(provider="gemini", model=gemini_model, use_mock=True)

    assert cfg.use_mock is True
    assert cfg.api_key is None


def test_unknown_provider_raises_error() -> None:
    """Unknown provider should raise a clear error."""
    with pytest.raises(ConfigurationError, match="Unknown provider"):
        Config(provider="unknown", model="some-model", use_mock=True)  # type: ignore[arg-type]


def test_config_str_and_repr_redact_api_key(gemini_model: str) -> None:
    """String representations must not leak secrets."""
    secret = "top-secret-key"
    cfg = Config(provider="gemini", model=gemini_model, api_key=secret)

    assert secret not in str(cfg)
    assert secret not in repr(cfg)
    assert "[REDACTED]" in str(cfg)
