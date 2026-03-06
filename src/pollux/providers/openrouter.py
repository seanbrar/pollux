"""OpenRouter Chat Completions provider implementation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

import httpx

from pollux.errors import APIError, ConfigurationError
from pollux.providers._errors import wrap_provider_error
from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import (
    Message,
    ProviderFileAsset,
    ProviderRequest,
    ProviderResponse,
)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

if TYPE_CHECKING:
    from pathlib import Path


class OpenRouterProvider:
    """OpenRouter provider backed by the HTTP API."""

    def __init__(self, api_key: str) -> None:
        """Initialize with an API key."""
        self.api_key = api_key
        self._client: Any = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return supported feature flags."""
        return ProviderCapabilities(
            persistent_cache=False,
            uploads=False,
            structured_outputs=False,
            reasoning=False,
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
            )
        return cast("httpx.AsyncClient", self._client)

    async def generate(
        self,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """Generate a response using OpenRouter chat completions."""
        if request.tools is not None or request.tool_choice is not None:
            raise ConfigurationError(
                "OpenRouter tool calling is not supported yet",
                hint="Remove tools/tool_choice for now. OpenRouter tool support is planned for a later release.",
            )

        _ = (
            request.previous_response_id
        )  # OpenRouter uses history replay, not ID-based continuation

        messages = _build_messages(
            request.parts,
            request.history,
            system_instruction=request.system_instruction,
        )
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

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
            raise APIError("OpenRouter returned a non-object response")

        return _parse_response(data)

    async def upload_file(self, path: Path, mime_type: str) -> ProviderFileAsset:
        """Raise because OpenRouter uploads are not supported yet."""
        _ = path, mime_type
        raise APIError("OpenRouter provider does not support file uploads yet")

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
        raise APIError("OpenRouter provider does not support context caching")

    async def aclose(self) -> None:
        """Close underlying async HTTP resources."""
        client = self._client
        if client is None:
            return
        self._client = None
        await client.aclose()


def _build_messages(
    parts: list[Any],
    history: list[Message] | None,
    *,
    system_instruction: str | None,
) -> list[dict[str, Any]]:
    """Build OpenRouter chat-completions messages from history and parts."""
    messages: list[dict[str, Any]] = []

    if system_instruction is not None:
        messages.append({"role": "system", "content": system_instruction})

    if history is not None:
        for item in history:
            if item.role == "tool" or item.tool_calls:
                raise ConfigurationError(
                    "OpenRouter tool history is not supported yet",
                    hint="Remove tool messages from history for now. OpenRouter tool support is planned for a later release.",
                )
            # Note: an empty Message.content sends `{"role": "assistant", "content": ""}`.
            # This is correct for assistant messages that only include tool calls.
            messages.append(
                {
                    "role": item.role,
                    "content": item.content,
                }
            )

    user_texts: list[str] = []
    for part in parts:
        normalized = _normalize_input_part(part)
        if normalized is not None:
            user_texts.append(normalized)

    user_text = "\n\n".join(text for text in user_texts if text)
    if user_text or not messages:
        messages.append({"role": "user", "content": user_text})

    return messages


def _normalize_input_part(part: Any) -> str | None:
    """Convert Pollux parts into OpenRouter-compatible text content."""
    if isinstance(part, str):
        return part

    if isinstance(part, dict) and isinstance(part.get("text"), str):
        return cast("str", part["text"])

    if isinstance(part, dict):
        if isinstance(part.get("file_path"), str):
            raise ConfigurationError(
                "OpenRouter local file inputs are not supported yet",
                hint="Use text sources for now. OpenRouter multimodal input support is planned for a later release.",
            )
        if isinstance(part.get("uri"), str):
            raise ConfigurationError(
                "OpenRouter URL inputs are not supported yet",
                hint="Use text sources for now. OpenRouter multimodal input support is planned for a later release.",
            )

    if isinstance(part, ProviderFileAsset):
        raise ConfigurationError(
            "OpenRouter does not support file assets",
            hint="Remove file sources; OpenRouter multimodal support is planned.",
        )

    if part is None:
        return None

    raise ConfigurationError(
        f"Unsupported OpenRouter input part: {type(part).__name__}",
        hint="Use plain text sources for now. OpenRouter multimodal input support is planned for a later release.",
    )


def _parse_response(data: Mapping[str, Any]) -> ProviderResponse:
    """Parse an OpenRouter chat-completions payload into ProviderResponse."""
    choices = data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(choice, Mapping):
        choice = {}

    message = choice.get("message")
    if not isinstance(message, Mapping):
        message = {}

    text = _extract_message_text(message.get("content"))
    finish_reason = choice.get("finish_reason")
    if not isinstance(finish_reason, str):
        finish_reason = None

    usage_raw = data.get("usage")
    usage: dict[str, int] = {}
    if isinstance(usage_raw, Mapping):
        prompt_tokens = usage_raw.get("prompt_tokens")
        completion_tokens = usage_raw.get("completion_tokens")
        total_tokens = usage_raw.get("total_tokens")
        if isinstance(prompt_tokens, int):
            usage["input_tokens"] = prompt_tokens
        if isinstance(completion_tokens, int):
            usage["output_tokens"] = completion_tokens
        if isinstance(total_tokens, int):
            usage["total_tokens"] = total_tokens

    response_id = data.get("id")
    return ProviderResponse(
        text=text,
        usage=usage,
        response_id=response_id if isinstance(response_id, str) else None,
        finish_reason=finish_reason,
    )


def _extract_message_text(content: Any) -> str:
    """Extract text from a chat-completions message content field."""
    if isinstance(content, str):
        return content

    if not isinstance(content, list):
        return ""

    text_parts: list[str] = []
    for item in content:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            text_parts.append(item["text"])
    return "\n\n".join(text_parts)


def _extract_error_message(response: httpx.Response) -> str:
    """Extract a useful error message from an OpenRouter HTTP response."""
    try:
        payload = response.json()
    except Exception:
        payload = None

    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message
        message = payload.get("message")
        if isinstance(message, str) and message:
            return message

    text = response.text.strip()
    if text:
        return text
    return f"HTTP {response.status_code}"
