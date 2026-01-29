"""High-signal tests for DX helpers that must never leak secrets."""

import os
from unittest.mock import patch

import pytest

from pollux.config import (
    audit_lines,
    check_environment,
    resolve_config,
    to_redacted_dict,
)

pytestmark = pytest.mark.unit


def test_check_environment_filters_and_redacts():
    """Only GEMINI_/POLLUX_ keys are returned and secrets are redacted."""
    env_vars = {
        "POLLUX_MODEL": "test-model",
        "GEMINI_API_KEY": "secret-key-123",
        "POLLUX_TOKEN": "secret-token-456",
        "OTHER_VAR": "should-not-appear",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        result = check_environment()

    assert set(result.keys()) == {"POLLUX_MODEL", "GEMINI_API_KEY", "POLLUX_TOKEN"}
    assert result["POLLUX_MODEL"] == "test-model"
    assert result["GEMINI_API_KEY"] == "***redacted***"
    assert result["POLLUX_TOKEN"] == "***redacted***"


def test_audit_lines_and_redacted_dict_never_leak_secrets():
    """Audit output and structured logs must redact sensitive fields."""
    cfg, sources = resolve_config(
        overrides={"api_key": "secret-key-123", "model": "test-model"}, explain=True
    )

    lines = audit_lines(cfg, sources)
    assert not any("secret-key-123" in line for line in lines)
    assert any(line.startswith("api_key:") and "REDACTED" in line for line in lines)

    redacted = to_redacted_dict(cfg)
    assert redacted["api_key"] == "***redacted***"
