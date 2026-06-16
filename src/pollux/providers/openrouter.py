"""OpenRouter Chat Completions provider implementation."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import time
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

import httpx

from pollux.errors import APIError, ConfigurationError
from pollux.providers import _compile
from pollux.providers._errors import wrap_provider_error
from pollux.providers._openai_compat import (
    extract_error_message,
    extract_finish_reason,
    extract_message_text,
    extract_response_id,
    first_choice_message,
    map_tool_choice,
    normalize_tools,
    parse_tool_calls,
    parse_usage,
    serialize_tool_calls,
)
from pollux.providers._utils import merge_provider_options, to_strict_schema
from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import (
    Message,
    ProviderFileAsset,
    ProviderResponse,
)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENROUTER_METADATA_TTL_S = 300.0
_OPENROUTER_REASONING_KEY = "openrouter_reasoning"
_OPENROUTER_REASONING_DETAILS_KEY = "openrouter_reasoning_details"

if TYPE_CHECKING:
    from pathlib import Path

    from pollux.config import Config
    from pollux.interaction.environment import EnvironmentSnapshot
    from pollux.interaction.input import Input
    from pollux.interaction.requirements import OutputRequirements


@dataclass(frozen=True)
class _OpenRouterModelMetadata:
    """Subset of model metadata used for capability checks."""

    input_modalities: frozenset[str]
    output_modalities: frozenset[str]
    supported_parameters: frozenset[str]


class OpenRouterProvider:
    """OpenRouter provider backed by the HTTP API."""

    def __init__(self, api_key: str) -> None:
        """Initialize with an API key."""
        self.api_key = api_key
        self._client: Any = None
        self._metadata_by_model: dict[str, _OpenRouterModelMetadata] = {}
        self._metadata_expires_at = 0.0
        self._metadata_lock = asyncio.Lock()

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return supported feature flags."""
        return ProviderCapabilities(
            persistent_cache=False,
            uploads=True,
            structured_outputs=True,
            reasoning=True,
            deferred_delivery=False,
            conversation=True,
            implicit_caching=False,
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Lazily initialize and return the shared async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=_OPENROUTER_BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=300.0,
            )
        return cast("httpx.AsyncClient", self._client)

    async def generate(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> ProviderResponse:
        """Generate a response using OpenRouter chat completions."""
        await self.validate_request(snapshot, input, requirements, config)

        # OpenRouter uses history replay, not ID-based continuation.
        history, _previous_response_id, provider_state = _compile.prior_turns(input)
        parts = _compile.request_parts(snapshot, input)
        response_schema = requirements.output_schema_json()
        tools = _compile.tool_dicts(snapshot)

        messages = _build_messages(
            parts,
            history or None,
            provider_state,
            system_instruction=_compile.system_instruction(snapshot),
        )
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
        }
        if requirements.temperature is not None:
            payload["temperature"] = requirements.temperature
        if requirements.top_p is not None:
            payload["top_p"] = requirements.top_p
        if requirements.max_tokens is not None:
            payload["max_tokens"] = requirements.max_tokens
        if tools is not None:
            payload["tools"] = normalize_tools(tools)
            mapped_tool_choice = map_tool_choice(requirements.tool_choice)
            if mapped_tool_choice is not None:
                payload["tool_choice"] = mapped_tool_choice
        if requirements.reasoning_effort is not None:
            payload["reasoning"] = {"effort": requirements.reasoning_effort}
        if response_schema is not None:
            strict_schema = to_strict_schema(response_schema)
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "pollux_structured_output",
                    "strict": True,
                    "schema": strict_schema,
                },
            }
        merge_provider_options(
            payload,
            requirements.provider_options_for("openrouter"),
            provider="openrouter",
        )

        client = self._get_client()
        try:
            response = await client.post("/chat/completions", json=payload)
            if response.is_error:
                raise httpx.HTTPStatusError(
                    _extract_error_message(response),
                    request=response.request,
                    response=response,
                )
            data = response.json()
        except ConfigurationError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="openrouter",
                phase="generate",
                allow_network_errors=True,
                message="OpenRouter generate failed",
            ) from e

        if not isinstance(data, dict):
            raise _openrouter_api_error(
                "OpenRouter returned a non-object response",
                phase="generate",
            )

        return _parse_response(data, response_schema=response_schema)

    async def validate_request(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> None:
        """Validate model-dependent OpenRouter behavior before dispatch."""
        if requirements.reasoning_budget_tokens is not None:
            raise ConfigurationError(
                "Provider does not support reasoning_budget_tokens",
                hint=(
                    "Use reasoning_effort, or choose a provider that accepts "
                    "an explicit reasoning token budget."
                ),
            )

        model = config.model
        metadata = await self._get_model_metadata(model)
        _require_text_io(metadata, model=model)

        tools = _compile.tool_dicts(snapshot)
        if tools is not None:
            _require_supported_parameter(
                metadata=metadata,
                model=model,
                feature_name="tool calling",
                parameter="tools",
            )
        if requirements.tool_choice is not None:
            _require_supported_parameter(
                metadata=metadata,
                model=model,
                feature_name="tool choice",
                parameter="tool_choice",
            )

        if requirements.output_schema_json() is not None:
            _require_supported_parameters_any(
                metadata=metadata,
                model=model,
                feature_name="structured outputs",
                parameters={"structured_outputs", "response_format"},
            )

        if requirements.reasoning_effort is not None:
            _require_supported_parameters_any(
                metadata=metadata,
                model=model,
                feature_name="reasoning controls",
                parameters={"reasoning", "reasoning_effort"},
            )

        _validate_input_modalities(
            metadata=metadata,
            model=model,
            parts=_compile.request_parts(snapshot, input),
        )

    async def upload_file(self, path: Path, mime_type: str) -> ProviderFileAsset:
        """Inline local files as data URLs for OpenRouter chat completions."""
        if not (mime_type.startswith("image/") or mime_type == "application/pdf"):
            raise ConfigurationError(
                f"Unsupported OpenRouter local mime type: {mime_type}",
                hint="OpenRouter currently supports local image files and PDFs only.",
            )

        try:
            data_url = _to_data_url(path.read_bytes(), mime_type)
        except Exception as e:
            raise _openrouter_api_error(
                f"Failed to read file for OpenRouter upload: {path}",
                phase="upload",
            ) from e

        return ProviderFileAsset(
            file_id=data_url,
            provider="openrouter",
            mime_type=mime_type,
            file_name=path.name,
        )

    async def create_cache(
        self,
        *,
        model: str,
        parts: list[Any],
        system_instruction: str | None = None,
        tools: list[dict[str, Any]] | list[Any] | None = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """Raise because OpenRouter does not expose Pollux cache handles."""
        _ = model, parts, system_instruction, tools, ttl_seconds
        raise _openrouter_api_error(
            "OpenRouter provider does not support context caching",
            phase="cache",
        )

    async def aclose(self) -> None:
        """Close underlying async HTTP resources."""
        client = self._client
        if client is None:
            return
        self._client = None
        await client.aclose()

    async def _get_model_metadata(self, model: str) -> _OpenRouterModelMetadata:
        """Return cached metadata for *model*, refreshing from OpenRouter as needed."""
        cached = self._metadata_by_model.get(model)
        if cached is not None and time.monotonic() < self._metadata_expires_at:
            return cached

        async with self._metadata_lock:
            cached = self._metadata_by_model.get(model)
            if cached is not None and time.monotonic() < self._metadata_expires_at:
                return cached

            metadata_by_model = await self._fetch_models()
            self._metadata_by_model = metadata_by_model
            self._metadata_expires_at = time.monotonic() + _OPENROUTER_METADATA_TTL_S

            refreshed = metadata_by_model.get(model)
            if refreshed is None:
                raise ConfigurationError(
                    f"OpenRouter model not found: {model!r}",
                    hint="Choose a valid OpenRouter model slug, for example 'openai/gpt-4.1-mini'.",
                )
            return refreshed

    async def _fetch_models(self) -> dict[str, _OpenRouterModelMetadata]:
        """Fetch and normalize the OpenRouter models catalog."""
        client = self._get_client()
        try:
            response = await client.get("/models")
            if response.is_error:
                raise httpx.HTTPStatusError(
                    _extract_error_message(response),
                    request=response.request,
                    response=response,
                )
            payload = response.json()
        except ConfigurationError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="openrouter",
                phase="metadata",
                allow_network_errors=True,
                message="OpenRouter model metadata lookup failed",
            ) from e

        if not isinstance(payload, Mapping):
            raise _openrouter_api_error(
                "OpenRouter models lookup returned a non-object response",
                phase="metadata",
            )

        data = payload.get("data")
        if not isinstance(data, list):
            raise _openrouter_api_error(
                "OpenRouter models lookup returned an invalid payload",
                phase="metadata",
            )

        metadata_by_model: dict[str, _OpenRouterModelMetadata] = {}
        for item in data:
            if not isinstance(item, Mapping):
                continue
            model_id = item.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue
            metadata_by_model[model_id] = _parse_model_metadata(item)

        return metadata_by_model


def _build_messages(
    parts: list[Any],
    history: list[Message] | None,
    provider_state: dict[str, Any] | None,
    *,
    system_instruction: str | None,
) -> list[dict[str, Any]]:
    """Build OpenRouter chat-completions messages from history and parts."""
    messages: list[dict[str, Any]] = []

    if system_instruction is not None:
        messages.append({"role": "system", "content": system_instruction})

    if history is not None:
        for idx, item in enumerate(history):
            item_provider_state = _get_history_item_provider_state(provider_state, idx)
            message = _history_message_to_openrouter(item, item_provider_state)
            if message is not None:
                messages.append(message)

    user_content: list[dict[str, Any]] = []
    for part in parts:
        normalized = _normalize_input_part(part)
        if normalized is not None:
            user_content.append(normalized)

    if user_content or not messages:
        messages.append(
            {
                "role": "user",
                "content": user_content or [{"type": "text", "text": ""}],
            }
        )

    return messages


def _history_message_to_openrouter(
    item: Message,
    item_provider_state: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Map a Pollux history message into OpenRouter chat-completions format."""
    if item.role == "tool":
        if not item.tool_call_id:
            return None
        return {
            "role": "tool",
            "tool_call_id": item.tool_call_id,
            "content": item.content,
        }

    message: dict[str, Any] = {"role": item.role, "content": item.content}
    tool_calls = serialize_tool_calls(item.tool_calls)
    if tool_calls:
        message["tool_calls"] = tool_calls

    reasoning = _extract_reasoning(item_provider_state)
    if reasoning is not None:
        message["reasoning"] = reasoning

    reasoning_details = _extract_reasoning_details(item_provider_state)
    if reasoning_details:
        message["reasoning_details"] = reasoning_details

    if (
        item.role == "assistant"
        and not item.content
        and not tool_calls
        and reasoning is None
        and not reasoning_details
    ):
        return None

    return message


def _normalize_input_part(part: Any) -> dict[str, Any] | None:
    """Convert Pollux parts into OpenRouter-compatible text content."""
    if isinstance(part, str):
        return {"type": "text", "text": part}

    if isinstance(part, dict) and isinstance(part.get("text"), str):
        return {"type": "text", "text": cast("str", part["text"])}

    if isinstance(part, dict):
        uri = part.get("uri")
        mime_type = part.get("mime_type")
        if isinstance(uri, str) and isinstance(mime_type, str):
            if mime_type.startswith("image/"):
                return {
                    "type": "image_url",
                    "image_url": {"url": uri},
                }
            if mime_type == "application/pdf":
                return {
                    "type": "file",
                    "file": {
                        "filename": _pdf_filename(uri=uri),
                        "file_data": uri,
                    },
                }
            raise ConfigurationError(
                f"Unsupported OpenRouter remote mime type: {mime_type}",
                hint="OpenRouter currently supports remote image URLs and PDF URLs only.",
            )

    if isinstance(part, ProviderFileAsset):
        if part.provider != "openrouter":
            raise _openrouter_api_error(
                f"OpenRouter cannot use {part.provider} file assets.",
                phase="generate",
            )
        if part.mime_type.startswith("image/"):
            return {
                "type": "image_url",
                "image_url": {"url": part.file_id},
            }
        if part.mime_type == "application/pdf":
            return {
                "type": "file",
                "file": {
                    "filename": _pdf_filename(
                        uri=part.file_id,
                        file_name=part.file_name,
                    ),
                    "file_data": part.file_id,
                },
            }
        raise ConfigurationError(
            f"Unsupported OpenRouter local mime type: {part.mime_type}",
            hint="OpenRouter currently supports local image files and PDFs only.",
        )

    if part is None:
        return None

    raise ConfigurationError(
        f"Unsupported OpenRouter input part: {type(part).__name__}",
        hint="OpenRouter currently supports text, images, and PDFs only.",
    )


def _parse_model_metadata(item: Mapping[str, Any]) -> _OpenRouterModelMetadata:
    """Normalize a models API entry into a compact metadata object."""
    architecture = item.get("architecture")
    if not isinstance(architecture, Mapping):
        architecture = {}

    input_modalities = architecture.get("input_modalities")
    output_modalities = architecture.get("output_modalities")
    supported_parameters = item.get("supported_parameters")

    return _OpenRouterModelMetadata(
        input_modalities=_normalize_str_set(input_modalities),
        output_modalities=_normalize_str_set(output_modalities),
        supported_parameters=_normalize_str_set(supported_parameters),
    )


def _normalize_str_set(value: Any) -> frozenset[str]:
    """Coerce a list-like metadata field into a lowercase string set."""
    if not isinstance(value, list):
        return frozenset()
    return frozenset(
        item.strip().lower() for item in value if isinstance(item, str) and item.strip()
    )


def _openrouter_api_error(
    message: str,
    *,
    phase: str,
    hint: str | None = None,
) -> APIError:
    """Return an OpenRouter-attributed APIError for direct boundary failures."""
    return APIError(message, hint=hint, provider="openrouter", phase=phase)


def _require_text_io(metadata: _OpenRouterModelMetadata, *, model: str) -> None:
    """Ensure a model can satisfy Pollux's current text-only result contract."""
    if "text" not in metadata.input_modalities:
        raise ConfigurationError(
            f"OpenRouter model {model!r} does not support text input",
            hint="Choose an OpenRouter chat model that accepts text input.",
        )
    if "text" not in metadata.output_modalities:
        raise ConfigurationError(
            f"OpenRouter model {model!r} does not support text output",
            hint="Choose an OpenRouter model with text output for Pollux's current result contract.",
        )


def _require_supported_parameter(
    *,
    metadata: _OpenRouterModelMetadata,
    model: str,
    feature_name: str,
    parameter: str,
) -> None:
    """Require a specific supported parameter for a model-gated feature."""
    if parameter in metadata.supported_parameters:
        return
    raise ConfigurationError(
        f"OpenRouter model {model!r} does not support {feature_name}",
        hint=f"Choose an OpenRouter model that supports {feature_name}.",
    )


def _require_supported_parameters_any(
    *,
    metadata: _OpenRouterModelMetadata,
    model: str,
    feature_name: str,
    parameters: set[str],
) -> None:
    """Require that metadata exposes at least one compatible parameter."""
    if not metadata.supported_parameters.isdisjoint(parameters):
        return
    raise ConfigurationError(
        f"OpenRouter model {model!r} does not support {feature_name}",
        hint=f"Choose an OpenRouter model that supports {feature_name}.",
    )


def _validate_input_modalities(
    *,
    metadata: _OpenRouterModelMetadata,
    model: str,
    parts: list[Any],
) -> None:
    """Differentiate unsupported-by-model vs unsupported-by-Pollux multimodal input."""
    for part in parts:
        modality = _requested_input_modality(part)
        if modality is None:
            continue
        if not _is_supported_multimodal_part(part):
            raise ConfigurationError(
                f"Unsupported OpenRouter input type for {modality} input",
                hint="OpenRouter currently supports image inputs and PDF files only.",
            )
        # PDFs are routed through OpenRouter's platform-level parser, which is
        # independent of the model's native input_modalities metadata.
        if _is_pdf_part(part):
            continue
        if modality not in metadata.input_modalities:
            raise ConfigurationError(
                f"OpenRouter model {model!r} does not support {modality} input",
                hint=f"Choose an OpenRouter model that supports {modality} input.",
            )


def _requested_input_modality(part: Any) -> str | None:
    """Infer the requested input modality for unsupported non-text parts."""
    mime_type: Any
    if isinstance(part, ProviderFileAsset):
        mime_type = part.mime_type
    elif isinstance(part, Mapping):
        mime_type = part.get("mime_type")
    else:
        return None

    if not isinstance(mime_type, str):
        return "file"
    if mime_type.startswith("image/"):
        return "image"
    return "file"


def _is_supported_multimodal_part(part: Any) -> bool:
    """Return True for the verified OpenRouter multimodal input subset."""
    mime_type: Any
    if isinstance(part, ProviderFileAsset):
        mime_type = part.mime_type
    elif isinstance(part, Mapping):
        mime_type = part.get("mime_type")
    else:
        return True

    return isinstance(mime_type, str) and (
        mime_type.startswith("image/") or mime_type == "application/pdf"
    )


def _is_pdf_part(part: Any) -> bool:
    """Return True when *part* is a PDF supported by OpenRouter parsing."""
    if isinstance(part, ProviderFileAsset):
        return part.mime_type == "application/pdf"
    if isinstance(part, Mapping):
        return part.get("mime_type") == "application/pdf"
    return False


def _to_data_url(data: bytes, mime_type: str) -> str:
    """Encode raw file bytes as a base64 data URL."""
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _pdf_filename(*, uri: str, file_name: str | None = None) -> str:
    """Return the filename OpenRouter expects for PDF content items."""
    if file_name:
        return file_name

    parsed = urlparse(uri)
    path_name = PurePosixPath(parsed.path).name
    if path_name:
        return path_name

    return "document.pdf"


def _parse_response(
    data: Mapping[str, Any],
    *,
    response_schema: dict[str, Any] | None,
) -> ProviderResponse:
    """Parse an OpenRouter chat-completions payload into ProviderResponse."""
    choice, message = first_choice_message(data)

    text = extract_message_text(message.get("content"))
    structured: dict[str, Any] | None = None
    if response_schema is not None and text:
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            structured = parsed

    usage = parse_usage(data.get("usage"))

    tool_calls = parse_tool_calls(message.get("tool_calls"))
    reasoning = message.get("reasoning")
    reasoning_details = _normalize_reasoning_details(message.get("reasoning_details"))
    provider_state: dict[str, Any] | None = None
    if isinstance(reasoning, str) and reasoning:
        provider_state = {_OPENROUTER_REASONING_KEY: reasoning}
    if reasoning_details:
        if provider_state is None:
            provider_state = {}
        provider_state[_OPENROUTER_REASONING_DETAILS_KEY] = reasoning_details
    return ProviderResponse(
        text=text,
        usage=usage,
        reasoning=reasoning if isinstance(reasoning, str) and reasoning else None,
        structured=structured,
        tool_calls=tool_calls if tool_calls else None,
        response_id=extract_response_id(data),
        finish_reason=extract_finish_reason(choice),
        provider_state=provider_state,
    )


def _extract_reasoning(item_provider_state: dict[str, Any] | None) -> str | None:
    """Return preserved OpenRouter reasoning text for a history item."""
    if item_provider_state is None:
        return None
    reasoning = item_provider_state.get(_OPENROUTER_REASONING_KEY)
    if isinstance(reasoning, str) and reasoning:
        return reasoning
    return None


def _normalize_reasoning_details(value: Any) -> list[dict[str, Any]]:
    """Return a JSON-serializable reasoning_details payload, if present."""
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, Mapping):
            normalized.append(dict(item))
    return normalized


def _extract_reasoning_details(
    item_provider_state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return preserved OpenRouter reasoning details for a history item."""
    if item_provider_state is None:
        return []
    return _normalize_reasoning_details(
        item_provider_state.get(_OPENROUTER_REASONING_DETAILS_KEY)
    )


def _get_history_item_provider_state(
    provider_state: dict[str, Any] | None, index: int
) -> dict[str, Any] | None:
    """Return provider_state for a specific history item."""
    if provider_state is None:
        return None

    history_states = provider_state.get("history")
    if not isinstance(history_states, list) or index >= len(history_states):
        return None

    item_provider_state = history_states[index]
    if not isinstance(item_provider_state, dict):
        return None

    return item_provider_state


def _extract_error_message(response: httpx.Response) -> str:
    """Extract an error message, preferring OpenRouter's nested upstream error.

    OpenRouter sometimes returns a stub ``error`` whose real message is nested
    under ``error.metadata.raw``. We surface that first, then fall back to the
    shared Chat Completions error shape.
    """
    try:
        payload = response.json()
    except Exception:
        payload = None

    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            nested_message = _extract_nested_provider_error_message(error)
            if nested_message is not None:
                return nested_message

    return extract_error_message(response)


def _extract_nested_provider_error_message(error: Mapping[str, Any]) -> str | None:
    """Extract a provider-specific nested error when OpenRouter returns a stub."""
    metadata = error.get("metadata")
    provider_name: str | None = None
    raw: str | None = None
    if isinstance(metadata, Mapping):
        candidate_provider = metadata.get("provider_name")
        if isinstance(candidate_provider, str) and candidate_provider:
            provider_name = candidate_provider
        candidate_raw = metadata.get("raw")
        if isinstance(candidate_raw, str) and candidate_raw.strip():
            raw = candidate_raw.strip()

    if raw is None:
        return None

    try:
        parsed = json.loads(raw)
    except Exception:
        nested = raw
    else:
        nested = _find_nested_message(parsed) or raw

    if provider_name is None:
        return nested
    return f"{provider_name}: {nested}"


def _find_nested_message(value: Any) -> str | None:
    """Return the first useful nested `message` string from JSON-like data."""
    if isinstance(value, Mapping):
        message = value.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

        error = value.get("error")
        if error is not None:
            nested = _find_nested_message(error)
            if nested is not None:
                return nested

        errors = value.get("errors")
        if errors is not None:
            nested = _find_nested_message(errors)
            if nested is not None:
                return nested

        for item in value.values():
            nested = _find_nested_message(item)
            if nested is not None:
                return nested
        return None

    if isinstance(value, list):
        for item in value:
            nested = _find_nested_message(item)
            if nested is not None:
                return nested

    return None
