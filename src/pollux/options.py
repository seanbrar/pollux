"""Execution options for additive API features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from pollux.errors import ConfigurationError

if TYPE_CHECKING:
    from pollux.result import ResultEnvelope

ReasoningEffort = Literal["low", "medium", "high"]
DeliveryMode = Literal["realtime", "deferred"]
ResponseSchemaInput = type[BaseModel] | dict[str, Any]


@dataclass(frozen=True)
class Options:
    """Optional execution features for `run()` and `run_many()`."""

    response_schema: ResponseSchemaInput | None = None
    reasoning_effort: ReasoningEffort | None = None
    delivery_mode: DeliveryMode = "realtime"
    history: list[dict[str, str]] | None = None
    continue_from: ResultEnvelope | None = None

    def __post_init__(self) -> None:
        """Validate option shapes early for clear errors."""
        if self.response_schema is not None and not (
            isinstance(self.response_schema, dict)
            or (
                isinstance(self.response_schema, type)
                and issubclass(self.response_schema, BaseModel)
            )
        ):
            raise ConfigurationError(
                "response_schema must be a Pydantic model class or JSON schema dict",
                hint="Pass a BaseModel subclass or a dict following JSON Schema.",
            )

        if self.history is not None and self.continue_from is not None:
            raise ConfigurationError(
                "history and continue_from are mutually exclusive",
                hint="Use exactly one conversation input source per call.",
            )
        if self.history is not None:
            if not isinstance(self.history, list):
                raise ConfigurationError(
                    "history must be a list of role/content messages",
                    hint="Pass history=[{'role': 'user', 'content': '...'}].",
                )
            for item in self.history:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("role"), str)
                    or not isinstance(item.get("content"), str)
                ):
                    raise ConfigurationError(
                        "history items must include string role and content fields",
                        hint=(
                            "Each item should look like "
                            "{'role': 'user', 'content': '...'}"
                        ),
                    )
        if self.continue_from is not None and not isinstance(self.continue_from, dict):
            raise ConfigurationError(
                "continue_from must be a prior Pollux result envelope",
                hint="Pass the dict returned by run() or run_many().",
            )

    def response_schema_json(self) -> dict[str, Any] | None:
        """Return JSON Schema for provider APIs."""
        schema = self.response_schema
        if schema is None:
            return None
        if isinstance(schema, dict):
            return schema
        return schema.model_json_schema()

    def response_schema_model(self) -> type[BaseModel] | None:
        """Return Pydantic schema class when one was provided."""
        schema = self.response_schema
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return schema
        return None
