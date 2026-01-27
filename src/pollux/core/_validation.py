"""Internal validation helpers used across core modules.

This module contains shared validation utilities that are used by multiple
core modules. These helpers centralize validation logic for type safety and
consistent error messages.
"""

from __future__ import annotations

import inspect
from types import MappingProxyType
import typing

T = typing.TypeVar("T")


def _freeze_mapping(
    m: dict[str, T] | typing.Mapping[str, T] | None,
) -> typing.Mapping[str, T] | None:
    """Return an immutable mapping view or None.

    Accepts dict or Mapping; wraps dicts in MappingProxyType while preserving type.
    """
    if m is None or isinstance(m, MappingProxyType):
        return m
    return MappingProxyType(dict(m))


def _is_tuple_of(value: object, typ: type | tuple[type, ...]) -> bool:
    return isinstance(value, tuple) and all(isinstance(v, typ) for v in value)


def _require(
    *,
    condition: bool,
    message: str,
    exc: type[Exception] = ValueError,
    field_name: str | None = None,
) -> None:
    """Centralized validation with optional field context for clearer errors."""
    if not condition:
        if field_name:
            enhanced_message = f"{field_name}: {message}"
            raise exc(enhanced_message)
        raise exc(message)


def _require_zero_arg_callable(func: typing.Any, field_name: str) -> None:
    """Validate callable takes no arguments for predictable execution."""
    _require(
        condition=callable(func),
        message="must be callable",
        field_name=field_name,
        exc=TypeError,
    )

    # Validate signature if introspectable
    try:
        sig = inspect.signature(func)
        has_required_params = any(
            p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
            for p in sig.parameters.values()
        )
        _require(
            condition=not has_required_params,
            message="must be a zero-argument callable",
            field_name=field_name,
            exc=TypeError,
        )
    except (ValueError, RuntimeError):
        # Some callables may not have introspectable signatures; acceptable
        # Note: Only catch signature inspection errors, not validation failures
        pass
