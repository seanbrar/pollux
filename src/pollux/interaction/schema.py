"""Response-schema helpers shared across the v2 interaction surface.

``OutputRequirements`` and the deferred entry points both accept a structured
output schema as either a Pydantic ``BaseModel`` subclass or a JSON Schema dict.
These helpers normalize that input into the JSON Schema, model class, and a
stable hash used to detect schema drift across deferred rehydration.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

#: A structured-output schema: a Pydantic model class or a JSON Schema dict.
ResponseSchemaInput = type[BaseModel] | dict[str, Any]


def response_schema_json(
    schema: ResponseSchemaInput | None,
) -> dict[str, Any] | None:
    """Return JSON Schema for provider APIs."""
    if schema is None:
        return None
    if isinstance(schema, dict):
        return schema
    return schema.model_json_schema()


def response_schema_model(
    schema: ResponseSchemaInput | None,
) -> type[BaseModel] | None:
    """Return a Pydantic model class when one was provided."""
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema
    return None


def response_schema_hash(schema: ResponseSchemaInput | None) -> str | None:
    """Return a stable hash of the JSON Schema."""
    normalized = response_schema_json(schema)
    if normalized is None:
        return None
    payload = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
