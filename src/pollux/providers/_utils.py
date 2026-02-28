"""Shared utilities for provider implementations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pollux.errors import APIError


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
