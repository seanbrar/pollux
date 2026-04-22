"""Local Chat Completions provider for self-hosted inference servers.

Pollux targets the OpenAI Chat Completions wire format here, not a specific
inference engine. The supported surface is deliberately narrow: text in, text or
JSON out. Model-native reasoning text is surfaced when returned, but reasoning
controls, file uploads, context caching, tool calling, and deferred delivery are
intentionally unsupported. Those belong to cloud providers, inference servers,
or application code, not to Pollux's orchestration layer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
from typing import TYPE_CHECKING, Any, cast

import httpx

from pollux.errors import APIError, ConfigurationError, walk_exception_chain
from pollux.providers._errors import wrap_provider_error
from pollux.providers._utils import to_strict_schema
from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import (
    Message,
    ProviderFileAsset,
    ProviderRequest,
    ProviderResponse,
)

if TYPE_CHECKING:
    from pathlib import Path

_LOCAL_TIMEOUT_S = 300.0


class LocalProvider:
    """Chat Completions provider for self-hosted OpenAI-compatible servers."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        """Initialize with the server's base URL and an optional auth token.

        Most local servers ignore the Authorization header; some require
        *any* value. We default to the literal ``"local"`` so both cases
        behave the same.
        """
        self._base_url = base_url
        self._api_key = api_key or "local"
        self._client: Any = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return supported feature flags (narrow by design)."""
        return ProviderCapabilities(
            persistent_cache=False,
            uploads=False,
            structured_outputs=True,
            reasoning=False,
            reasoning_budget_tokens=False,
            deferred_delivery=False,
            conversation=True,
            implicit_caching=False,
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Lazily initialize the shared async HTTP client."""
        if self._client is None:
            base_url = self._base_url
            if not base_url.endswith("/"):
                base_url += "/"
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=_LOCAL_TIMEOUT_S,
                limits=httpx.Limits(
                    max_connections=None, max_keepalive_connections=None
                ),
            )
        return cast("httpx.AsyncClient", self._client)

    async def validate_request(self, request: ProviderRequest) -> None:
        """Fail fast on features the local provider does not support."""
        if request.reasoning_budget_tokens is not None:
            raise ConfigurationError(
                "Local provider does not support reasoning_budget_tokens",
                hint="Remove reasoning_budget_tokens.",
            )
        if request.reasoning_effort is not None:
            raise ConfigurationError(
                "Local provider does not support reasoning_effort controls",
                hint=(
                    "Local can surface model-native reasoning when the server "
                    "returns it, but Pollux does not send portable local "
                    "reasoning controls. Remove reasoning_effort."
                ),
            )
        if request.tools is not None or request.tool_choice is not None:
            raise ConfigurationError(
                "Local provider does not support tool calling",
                hint=(
                    "Tool calling is out of scope for the local provider. "
                    "Use OpenAI, Gemini, or OpenRouter for tool use."
                ),
            )
        if request.history is not None:
            for item in request.history:
                if (
                    item.role == "tool"
                    or item.tool_call_id is not None
                    or item.tool_calls is not None
                ):
                    raise ConfigurationError(
                        "Local provider does not support tool-call history",
                        hint=(
                            "Start a fresh text-only local conversation, summarize "
                            "tool results into plain text, or use a provider with "
                            "tool calling."
                        ),
                    )
        for part in request.parts:
            if not _is_text_part(part):
                raise ConfigurationError(
                    "Local provider does not support file or multimodal input",
                    hint=(
                        "Pass file content as text via Source.from_text(). "
                        "Images, PDFs, and remote URIs are not supported."
                    ),
                )

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        """Generate a response via OpenAI-compatible Chat Completions."""
        await self.validate_request(request)

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
        if request.response_schema is not None:
            strict_schema = to_strict_schema(request.response_schema)
            # Servers that support Chat Completions JSON schema mode can map this
            # to their own constrained decoding implementation.
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "pollux_structured_output",
                    "schema": strict_schema,
                    "strict": True,
                },
            }

        client = self._get_client()
        try:
            response = await client.post("chat/completions", json=payload)
            if response.is_error:
                raise httpx.HTTPStatusError(
                    _extract_error_message(response),
                    request=response.request,
                    response=response,
                )
            data = response.json()
        except asyncio.CancelledError:
            raise
        except (ConfigurationError, APIError):
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="local",
                phase="generate",
                allow_network_errors=True,
                message="Local provider generate failed",
                hint=_hint_for_local_error(e, base_url=self._base_url),
            ) from e

        if not isinstance(data, dict):
            raise _local_api_error(
                "Local server returned a non-object response",
                phase="generate",
                hint="Check your server's logs; the response shape is unexpected.",
            )

        return _parse_response(data, response_schema=request.response_schema)

    async def upload_file(self, path: Path, mime_type: str) -> ProviderFileAsset:
        """Reject uploads because local provider takes inline content only."""
        _ = path, mime_type
        raise _local_api_error(
            "Local provider does not support file uploads",
            phase="upload",
            hint="Pass file content as text via Source.from_text().",
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
        """Reject cache creation because local provider has no persistent cache."""
        _ = model, parts, system_instruction, tools, ttl_seconds
        raise _local_api_error(
            "Local provider does not support context caching",
            phase="cache",
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        client = self._client
        if client is None:
            return
        self._client = None
        await client.aclose()


def _is_text_part(part: Any) -> bool:
    """Return True when *part* is plain text the local provider can send inline.

    Mirrors OpenRouter's input-part discrimination: strings and
    text-only dicts pass; ProviderFileAsset and dicts carrying
    ``uri``/``mime_type`` are rejected.
    """
    if part is None:
        return True
    if isinstance(part, str):
        return True
    if isinstance(part, ProviderFileAsset):
        return False
    if isinstance(part, Mapping):
        if "uri" in part or "mime_type" in part:
            return False
        return isinstance(part.get("text"), str)
    return False


def _build_messages(
    parts: list[Any],
    history: list[Message] | None,
    *,
    system_instruction: str | None,
) -> list[dict[str, Any]]:
    """Build Chat Completions messages from history and text parts."""
    messages: list[dict[str, Any]] = []

    if system_instruction is not None:
        messages.append({"role": "system", "content": system_instruction})

    if history is not None:
        for item in history:
            message = _history_message(item)
            if message is not None:
                messages.append(message)

    user_text = _join_text_parts(parts)
    if user_text or not messages:
        messages.append({"role": "user", "content": user_text})

    return messages


def _history_message(item: Message) -> dict[str, Any] | None:
    """Map a Pollux history message to Chat Completions format.

    Tool-call history is unsupported and rejected by ``validate_request`` before
    dispatch; this helper only maps text-only conversation turns.
    """
    if item.role == "tool":
        return None
    if not item.content:
        return None
    return {"role": item.role, "content": item.content}


def _join_text_parts(parts: list[Any]) -> str:
    """Concatenate text parts into a single user message body."""
    texts: list[str] = []
    for part in parts:
        if isinstance(part, str):
            texts.append(part)
        elif isinstance(part, Mapping) and isinstance(part.get("text"), str):
            texts.append(cast("str", part["text"]))
    return "\n\n".join(texts)


def _parse_response(
    data: Mapping[str, Any],
    *,
    response_schema: dict[str, Any] | None,
) -> ProviderResponse:
    """Parse a Chat Completions payload into ProviderResponse.

    JSON parsing is opportunistic: a non-JSON response despite JSON mode
    produces ``structured=None`` (matching OpenRouter). result.py then
    surfaces this as a ``None`` entry in the envelope's ``structured``
    list and marks status accordingly. We deliberately do not raise here
    because local servers vary in their JSON-mode fidelity, and a structured=None
    slot is the established Pollux signal for "did not produce structured
    output." Revisit if real-world use shows this silent path confuses users.
    """
    choices = data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(choice, Mapping):
        choice = {}

    message = choice.get("message")
    if not isinstance(message, Mapping):
        message = {}

    text = _extract_message_text(message.get("content"))
    reasoning_content = message.get("reasoning_content")
    reasoning = (
        reasoning_content
        if isinstance(reasoning_content, str) and reasoning_content
        else None
    )

    structured: Any = None
    if response_schema is not None and text:
        try:
            structured = json.loads(text)
        except Exception:
            structured = None

    finish_reason = choice.get("finish_reason")
    if not isinstance(finish_reason, str):
        finish_reason = None

    usage = _parse_usage(data.get("usage"))

    response_id = data.get("id")
    return ProviderResponse(
        text=text,
        usage=usage,
        reasoning=reasoning,
        structured=structured,
        response_id=response_id if isinstance(response_id, str) else None,
        finish_reason=finish_reason,
    )


def _extract_message_text(content: Any) -> str:
    """Extract text from a Chat Completions message content field."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    text_parts: list[str] = []
    for item in content:
        if isinstance(item, Mapping) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    return "\n\n".join(text_parts)


def _parse_usage(usage_raw: Any) -> dict[str, int]:
    """Extract token usage from a Chat Completions response."""
    if not isinstance(usage_raw, Mapping):
        return {}
    usage: dict[str, int] = {}
    prompt = usage_raw.get("prompt_tokens")
    completion = usage_raw.get("completion_tokens")
    total = usage_raw.get("total_tokens")
    if isinstance(prompt, int):
        usage["input_tokens"] = prompt
    if isinstance(completion, int):
        usage["output_tokens"] = completion
    if isinstance(total, int):
        usage["total_tokens"] = total
    details = usage_raw.get("prompt_tokens_details")
    if isinstance(details, Mapping):
        cached = details.get("cached_tokens")
        if isinstance(cached, int):
            usage["cached_tokens"] = cached
    return usage


def _hint_for_local_error(exc: BaseException, *, base_url: str) -> str | None:
    """Return a local-specific hint for common failure shapes."""
    for e in walk_exception_chain(exc):
        if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
            return (
                f"Cannot reach local server at {base_url}. "
                f"Is it running? Check POLLUX_LOCAL_BASE_URL."
            )
        if isinstance(e, httpx.ReadTimeout):
            return (
                f"Local inference timed out after {_LOCAL_TIMEOUT_S:.0f}s. "
                f"The model may be too slow for your hardware."
            )

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = (exc.response.text or "").lower()
        if status == 404 or ("model" in body and "not found" in body):
            return (
                "Model not found on the local server. "
                "Load the model (e.g., 'ollama pull <model>') or check the "
                "model name."
            )
        if status >= 500:
            return (
                "Local server error. The server may be overloaded or the "
                "model may have crashed; check server logs."
            )
    return None


def _extract_error_message(response: httpx.Response) -> str:
    """Extract a useful error message from a local server HTTP response."""
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
    return text or f"HTTP {response.status_code}"


def _local_api_error(
    message: str,
    *,
    phase: str,
    hint: str | None = None,
) -> APIError:
    """Return a local-attributed APIError for direct boundary failures."""
    return APIError(message, hint=hint, provider="local", phase=phase)
