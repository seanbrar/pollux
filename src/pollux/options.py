"""Execution options for additive API features."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from pollux.errors import ConfigurationError

if TYPE_CHECKING:
    from pollux.result import ResultEnvelope

ReasoningEffort = str
DeliveryMode = Literal["realtime", "deferred"]
ResponseSchemaInput = type[BaseModel] | dict[str, Any]


@dataclass(frozen=True)
class Options:
    """Optional execution features for `run()` and `run_many()`."""

    #: Optional system-level instruction for model behavior.
    system_instruction: str | None = None
    #: Pydantic ``BaseModel`` subclass or JSON Schema dict for structured output.
    response_schema: ResponseSchemaInput | None = None

    #: Core tool calling parameters
    tools: list[dict[str, Any]] | None = None
    tool_choice: Literal["auto", "required", "none"] | dict[str, Any] | None = None

    #: Generation tuning parameters
    temperature: float | None = None
    top_p: float | None = None

    #: Controls model thinking depth; passed through to the provider.
    reasoning_effort: ReasoningEffort | None = None
    # TODO: implement deferred delivery via provider batch APIs.
    delivery_mode: DeliveryMode = "realtime"
    #: Mutually exclusive with *continue_from*.
    history: list[dict[str, Any]] | None = None
    #: Mutually exclusive with *history*.
    continue_from: ResultEnvelope | None = None
    #: Hard limit on the model's total output tokens. Provider-specific semantics.
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        """Validate option shapes early for clear errors."""
        if self.system_instruction is not None and not isinstance(
            self.system_instruction, str
        ):
            raise ConfigurationError(
                "system_instruction must be a string",
                hint="Pass system_instruction='You are a concise assistant.'",
            )

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

        if self.max_tokens is not None and (
            not isinstance(self.max_tokens, int) or self.max_tokens <= 0
        ):
            raise ConfigurationError(
                "max_tokens must be a positive integer",
                hint="Pass max_tokens=16384 or greater for thinking models.",
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
                if not isinstance(item, dict) or not isinstance(item.get("role"), str):
                    raise ConfigurationError(
                        "history items must be dicts with a string 'role' field",
                        hint=(
                            "Each item needs at least {'role': 'user', ...}. "
                            "Tool messages may omit 'content' or include extra "
                            "keys like 'tool_call_id'."
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
