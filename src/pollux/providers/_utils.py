"""Shared utilities for provider implementations."""

from __future__ import annotations

from contextlib import suppress
from copy import deepcopy
from typing import Any

from pollux.errors import APIError, ConfigurationError


def to_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize a JSON schema for strict structured-output requirements.

    Ensures that for all 'object' types:
    1. additionalProperties is False
    2. All defined properties are listed in 'required'
    """
    normalized = deepcopy(schema)

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node

        updated: dict[str, Any] = {}
        for key, value in node.items():
            updated[key] = walk(value)

        if updated.get("type") == "object" or "properties" in updated:
            properties = updated.get("properties", {})
            if isinstance(properties, dict):
                updated["additionalProperties"] = False
                if "required" not in updated:
                    updated["required"] = list(properties.keys())

        return updated

    result = walk(normalized)
    if not isinstance(result, dict):
        raise APIError("Invalid response_schema: expected object schema")
    return result


def merge_provider_options(
    target: dict[str, Any],
    provider_options: dict[str, Any] | None,
    *,
    provider: str,
) -> None:
    """Merge raw provider options while preventing silent core-field overrides."""
    if provider_options is None:
        return
    overlaps = sorted(set(target).intersection(provider_options))
    if overlaps:
        joined = ", ".join(repr(key) for key in overlaps)
        raise ConfigurationError(
            f"provider_options for {provider!r} overlap with Pollux-managed keys: {joined}",
            hint=(
                "Set this parameter through Pollux's first-class options, or "
                "remove the overlapping key from provider_options."
            ),
        )
    target.update(provider_options)


def jsonable_provider_artifact(value: Any) -> Any:
    """Return a JSON-like representation for best-effort diagnostics."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [jsonable_provider_artifact(item) for item in value]
    if isinstance(value, tuple):
        return [jsonable_provider_artifact(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): jsonable_provider_artifact(item)
            for key, item in value.items()
            if not callable(item)
        }
    if hasattr(value, "model_dump"):
        with suppress(Exception):
            return jsonable_provider_artifact(value.model_dump(exclude_none=True))
    if hasattr(value, "to_dict"):
        with suppress(Exception):
            return jsonable_provider_artifact(value.to_dict())
    attrs: dict[str, Any] = {}
    for key in dir(value):
        if key.startswith("_"):
            continue
        with suppress(Exception):
            item = getattr(value, key)
            if callable(item):
                continue
            if isinstance(item, (str, int, float, bool, list, tuple, dict, type(None))):
                attrs[key] = jsonable_provider_artifact(item)
    return attrs or repr(value)
