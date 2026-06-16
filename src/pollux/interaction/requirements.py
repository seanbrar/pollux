"""``OutputRequirements``: what kind of response Pollux should ask for.

This is the per-generation requirement bundle split out of v1.x ``Options``:
structured-output schema, generation controls, reasoning controls, tool choice,
and a scoped provider-options escape hatch. It is not environment — it carries
no stable sources, tool declarations, cache handles, history, or auth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, get_args

from pollux.config import ProviderName
from pollux.errors import ConfigurationError
from pollux.interaction.schema import (
    ResponseSchemaInput,
    response_schema_hash,
    response_schema_json,
    response_schema_model,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

#: ``"auto"`` / ``"required"`` / ``"none"``, or a provider-specific dict.
ToolChoice = Literal["auto", "required", "none"] | dict[str, Any]


@dataclass(frozen=True, slots=True)
class OutputRequirements:
    """Per-interaction controls for the response Pollux asks the model to produce."""

    output_schema: ResponseSchemaInput | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int | None = None
    reasoning_effort: str | None = None
    reasoning_budget_tokens: int | None = None
    tool_choice: ToolChoice | None = None
    #: Raw provider-scoped generation options keyed by provider name. Passed
    #: through without normalization at the active provider boundary.
    provider_options: dict[str, dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        """Validate requirement shapes early for clear errors."""
        if self.output_schema is not None and not (
            isinstance(self.output_schema, dict)
            or (
                isinstance(self.output_schema, type)
                and _is_base_model(self.output_schema)
            )
        ):
            raise ConfigurationError(
                "output_schema must be a Pydantic model class or JSON schema dict",
                hint="Pass a BaseModel subclass or a dict following JSON Schema.",
            )
        if self.max_tokens is not None and (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or self.max_tokens <= 0
        ):
            raise ConfigurationError(
                "max_tokens must be a positive integer",
                hint="Pass max_tokens=16384 or greater for thinking models.",
            )
        if self.reasoning_budget_tokens is not None and (
            isinstance(self.reasoning_budget_tokens, bool)
            or not isinstance(self.reasoning_budget_tokens, int)
            or self.reasoning_budget_tokens < 0
        ):
            raise ConfigurationError(
                "reasoning_budget_tokens must be a non-negative integer",
                hint="Pass reasoning_budget_tokens=0 or a larger integer.",
            )
        if (
            self.reasoning_effort is not None
            and self.reasoning_budget_tokens is not None
        ):
            raise ConfigurationError(
                "reasoning_effort and reasoning_budget_tokens are mutually exclusive",
                hint="Choose either qualitative effort or an explicit token budget.",
            )
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise ConfigurationError(
                "seed must be an integer",
                hint="Pass seed=42 for reproducible sampling where supported.",
            )
        if self.provider_options is not None:
            _validate_provider_options(self.provider_options)

    def output_schema_json(self) -> dict[str, Any] | None:
        """Return JSON Schema for provider APIs."""
        return response_schema_json(self.output_schema)

    def output_schema_model(self) -> type[BaseModel] | None:
        """Return the Pydantic model class when one was provided."""
        return response_schema_model(self.output_schema)

    def output_schema_hash(self) -> str | None:
        """Return a stable hash of the JSON Schema."""
        return response_schema_hash(self.output_schema)

    def provider_options_for(self, provider: str) -> dict[str, Any] | None:
        """Return raw generation options for the active provider."""
        if self.provider_options is None:
            return None
        payload = self.provider_options.get(provider)
        return dict(payload) if payload is not None else None


def _is_base_model(candidate: type[Any]) -> bool:
    """Return True when *candidate* is a Pydantic ``BaseModel`` subclass."""
    from pydantic import BaseModel

    return issubclass(candidate, BaseModel)


def _validate_provider_options(
    provider_options: dict[str, dict[str, Any]],
) -> None:
    """Validate the scoped provider-options escape hatch shape."""
    if not isinstance(provider_options, dict):
        raise ConfigurationError(
            "provider_options must be a dictionary keyed by provider name",
            hint="Pass provider_options={'openai': {'frequency_penalty': 0.5}}.",
        )
    supported = set(get_args(ProviderName))
    for provider, payload in provider_options.items():
        if provider not in supported:
            allowed = ", ".join(sorted(supported))
            raise ConfigurationError(
                f"Unknown provider_options provider: {provider!r}",
                hint=f"Use one of: {allowed}.",
            )
        if not isinstance(payload, dict):
            raise ConfigurationError(
                f"provider_options[{provider!r}] must be a dictionary",
                hint="Pass raw provider parameters as a dictionary.",
            )
