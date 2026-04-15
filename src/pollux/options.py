"""Execution options for additive API features."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from pollux.errors import ConfigurationError

if TYPE_CHECKING:
    from pollux.cache import CacheHandle
    from pollux.result import ResultEnvelope

ReasoningEffort = str
# Intentionally kept as plain ``str`` instead of ``Literal[...]`` so IDEs do
# not advertise the legacy ``"deferred"`` value in completions while older
# callers can still pass it during migration. Runtime validation below keeps
# the accepted set narrow and provides upgrade guidance.
DeliveryMode = str
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
    #: Controls provider reasoning token budget where supported.
    reasoning_budget_tokens: int | None = None
    #: Legacy compatibility shim. Realtime remains the only supported value.
    delivery_mode: DeliveryMode = "realtime"
    #: Mutually exclusive with *continue_from*.
    history: list[dict[str, Any]] | None = None
    #: Mutually exclusive with *history*.
    continue_from: ResultEnvelope | None = None
    #: Hard limit on the model's total output tokens. Provider-specific semantics.
    max_tokens: int | None = None
    #: Persistent context cache obtained from ``create_cache()``.
    cache: CacheHandle | None = None
    #: Controls implicit model-level caching (e.g., Anthropic prefix caching).
    #: Defaults to True for a single provider call, False for multi-call fan-out.
    implicit_caching: bool | None = None

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
        if self.reasoning_budget_tokens is not None and (
            isinstance(self.reasoning_budget_tokens, bool)
            or not isinstance(self.reasoning_budget_tokens, int)
            or self.reasoning_budget_tokens < 0
        ):
            raise ConfigurationError(
                "reasoning_budget_tokens must be a non-negative integer",
                hint=(
                    "Providers enforce their own minimums: Gemini 2.5 Flash "
                    "accepts 0 to disable thinking; Anthropic requires at "
                    "least 1024; Gemini 2.5 Pro requires at least 128."
                ),
            )
        if (
            self.reasoning_effort is not None
            and self.reasoning_budget_tokens is not None
        ):
            raise ConfigurationError(
                "reasoning_effort and reasoning_budget_tokens are mutually exclusive",
                hint="Choose either qualitative effort or an explicit token budget.",
            )

        # Keep this runtime guard even though ``delivery_mode`` is typed as
        # ``str`` on purpose; the loose annotation is a UX choice for editor
        # autocomplete, not a widening of the supported values.
        if self.delivery_mode not in {"realtime", "deferred"}:
            raise ConfigurationError(
                "delivery_mode must be 'realtime' or 'deferred'",
                hint=(
                    "Remove delivery_mode, keep the default realtime mode, "
                    "or use delivery_mode='deferred' only as a migration shim."
                ),
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
        if self.cache is not None:
            from pollux.cache import CacheHandle

            if not isinstance(self.cache, CacheHandle):
                raise ConfigurationError(
                    "cache must be a CacheHandle from create_cache()",
                    hint="Call create_cache() first, then pass Options(cache=handle).",
                )

    def response_schema_json(self) -> dict[str, Any] | None:
        """Return JSON Schema for provider APIs."""
        return response_schema_json(self.response_schema)

    def response_schema_model(self) -> type[BaseModel] | None:
        """Return Pydantic schema class when one was provided."""
        return response_schema_model(self.response_schema)

    def response_schema_hash(self) -> str | None:
        """Return a stable hash of the JSON Schema."""
        return response_schema_hash(self.response_schema)
