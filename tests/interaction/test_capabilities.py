"""Unit tests for v2 capability resolution (Config declarations vs static)."""

from __future__ import annotations

from typing import Any

import pytest

from pollux.errors import ConfigurationError
from pollux.interaction.capabilities import resolve_capabilities
from pollux.providers.base import ProviderCapabilities

pytestmark = pytest.mark.unit


def _static(**overrides: Any) -> ProviderCapabilities:
    base: dict[str, Any] = {"persistent_cache": False, "uploads": False}
    base.update(overrides)
    return ProviderCapabilities(**base)


def test_none_declaration_returns_static_unchanged():
    static = _static(uploads=True)
    assert resolve_capabilities(static, None) is static


def test_empty_declaration_returns_static():
    static = _static()
    assert resolve_capabilities(static, {}) is static


def test_declaration_caps_a_supported_capability():
    static = _static(structured_outputs=True)
    resolved = resolve_capabilities(static, {"structured_outputs": False})
    assert resolved.structured_outputs is False


def test_declaration_asserts_an_unsupported_capability():
    static = _static(structured_outputs=False)
    resolved = resolve_capabilities(static, {"structured_outputs": True})
    assert resolved.structured_outputs is True


def test_undeclared_capabilities_fall_back_to_static():
    static = _static(uploads=True, structured_outputs=False)
    resolved = resolve_capabilities(static, {"structured_outputs": True})
    assert resolved.uploads is True


def test_unknown_capability_name_raises():
    with pytest.raises(ConfigurationError, match="Unknown capability"):
        resolve_capabilities(_static(), {"streaming": True})


def test_non_bool_capability_value_raises():
    with pytest.raises(ConfigurationError, match="must be a boolean"):
        resolve_capabilities(_static(), {"structured_outputs": "yes"})  # type: ignore[dict-item]
