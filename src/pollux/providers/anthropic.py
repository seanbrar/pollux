"""Anthropic Messages API provider."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from pollux.errors import APIError
from pollux.providers._errors import wrap_provider_error
from pollux.providers._utils import to_strict_schema
from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import ProviderRequest, ProviderResponse, ToolCall

if TYPE_CHECKING:
    from pathlib import Path


class AnthropicProvider:
    """Anthropic Messages API provider."""

    def __init__(self, api_key: str) -> None:
        """Initialize with an API key."""
        self.api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazily initialize and return the async Anthropic client."""
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as e:
                raise APIError(
                    "anthropic package not installed",
                    hint="uv pip install anthropic",
                ) from e
            self._client = AsyncAnthropic(api_key=self.api_key)
        return self._client

    @property
    def supports_caching(self) -> bool:
        """Whether this provider supports context caching."""
        return self.capabilities.caching

    @property
    def supports_uploads(self) -> bool:
        """Whether this provider supports file uploads."""
        return self.capabilities.uploads

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return supported feature flags."""
        return ProviderCapabilities(
            caching=False,
            uploads=False,
            structured_outputs=True,
            reasoning=False,
            deferred_delivery=False,
            conversation=True,
        )

    async def generate(
        self,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """Generate a response using Anthropic's Messages API."""
        client = self._get_client()

        model = request.model
        parts = request.parts
        system_instruction = request.system_instruction
        response_schema = request.response_schema
        temperature = request.temperature
        top_p = request.top_p
        tools = request.tools
        tool_choice = request.tool_choice
        history = request.history

        # No Anthropic equivalents or deferred features.
        _ = request.cache_name
        _ = request.reasoning_effort
        _ = request.previous_response_id

        # Build the messages list from history + current parts.
        # Anthropic requires strict user/assistant role alternation, so
        # consecutive same-role messages must be merged.
        messages: list[dict[str, Any]] = []

        if history:
            for item in history:
                if item.role == "tool":
                    call_id = item.tool_call_id
                    if not call_id:
                        continue
                    _append_message(
                        messages,
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": call_id,
                                    "content": item.content or "",
                                }
                            ],
                        },
                    )
                elif item.role == "assistant":
                    content_blocks: list[dict[str, Any]] = []
                    if item.content:
                        content_blocks.append(
                            {
                                "type": "text",
                                "text": item.content,
                            }
                        )
                    if item.tool_calls:
                        for tc in item.tool_calls:
                            try:
                                args = json.loads(tc.arguments)
                            except Exception:
                                args = {}
                            content_blocks.append(
                                {
                                    "type": "tool_use",
                                    "id": tc.id,
                                    "name": tc.name,
                                    "input": args,
                                }
                            )
                    if content_blocks:
                        _append_message(
                            messages,
                            {
                                "role": "assistant",
                                "content": content_blocks,
                            },
                        )
                elif item.role == "user":
                    if item.content:
                        _append_message(
                            messages,
                            {
                                "role": "user",
                                "content": item.content,
                            },
                        )

        # Build user content from current parts.
        user_content: list[dict[str, Any]] = []
        for part in parts:
            normalized = _normalize_input_part(part)
            if normalized is not None:
                user_content.append(normalized)

        has_real_content = False
        for c in user_content:
            if c.get("type") != "text" or c.get("text"):
                has_real_content = True
                break

        if not user_content:
            user_content.append({"type": "text", "text": ""})

        if has_real_content or not messages:
            _append_message(messages, {"role": "user", "content": user_content})

        # Build create kwargs.
        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": 8192,
        }

        if system_instruction:
            create_kwargs["system"] = system_instruction
        if temperature is not None:
            create_kwargs["temperature"] = temperature
        if top_p is not None:
            create_kwargs["top_p"] = top_p

        # Tool definitions.
        if tools is not None:
            anthropic_tools: list[dict[str, Any]] = []
            for t in tools:
                if "name" in t:
                    tool_def: dict[str, Any] = {
                        "name": t["name"],
                        "input_schema": t.get("parameters", {"type": "object"}),
                    }
                    if "description" in t:
                        tool_def["description"] = t["description"]
                    anthropic_tools.append(tool_def)
            if anthropic_tools:
                create_kwargs["tools"] = anthropic_tools

            if tool_choice is not None:
                if isinstance(tool_choice, str):
                    if tool_choice == "required":
                        create_kwargs["tool_choice"] = {"type": "any"}
                    elif tool_choice in ("auto", "none"):
                        create_kwargs["tool_choice"] = {"type": tool_choice}
                elif isinstance(tool_choice, dict) and "name" in tool_choice:
                    create_kwargs["tool_choice"] = {
                        "type": "tool",
                        "name": tool_choice["name"],
                    }

        # Structured output via output_config.format.
        if response_schema is not None:
            strict_schema = to_strict_schema(response_schema)
            create_kwargs["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": strict_schema,
                }
            }

        try:
            response = await client.messages.create(**create_kwargs)
            return _parse_response(response, response_schema=response_schema)
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="anthropic",
                phase="generate",
                allow_network_errors=True,
                message="Anthropic generate failed",
            ) from e

    async def upload_file(self, path: Path, mime_type: str) -> str:
        """Raise because Anthropic file uploads are not supported."""
        _ = path, mime_type
        raise APIError("Anthropic provider does not support file uploads")

    async def create_cache(
        self,
        *,
        model: str,
        parts: list[Any],
        system_instruction: str | None = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """Raise because Anthropic caching is deferred."""
        _ = model, parts, system_instruction, ttl_seconds
        raise APIError("Anthropic provider does not support context caching")

    async def aclose(self) -> None:
        """Close underlying async client resources."""
        client = self._client
        if client is None:
            return
        self._client = None
        await client.close()


def _parse_response(
    response: Any, *, response_schema: dict[str, Any] | None
) -> ProviderResponse:
    """Parse an Anthropic Message response into ProviderResponse."""
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for block in getattr(response, "content", []):
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_parts.append(getattr(block, "text", ""))
        elif block_type == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    arguments=json.dumps(getattr(block, "input", {})),
                )
            )

    text = "\n\n".join(text_parts) if text_parts else ""

    # Usage extraction.
    usage: dict[str, int] = {}
    usage_raw = getattr(response, "usage", None)
    if usage_raw is not None:
        input_tokens = int(getattr(usage_raw, "input_tokens", 0))
        output_tokens = int(getattr(usage_raw, "output_tokens", 0))
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }

    # Finish reason mapping.
    stop_reason = getattr(response, "stop_reason", None)
    finish_reason = _normalize_stop_reason(stop_reason)

    # Response ID.
    response_id = getattr(response, "id", None)

    # Structured output extraction.
    structured: Any = None
    if response_schema is not None and text:
        try:
            structured = json.loads(text)
        except Exception:
            structured = None

    return ProviderResponse(
        text=text,
        usage=usage,
        reasoning=None,
        structured=structured,
        tool_calls=tool_calls if tool_calls else None,
        response_id=response_id if isinstance(response_id, str) else None,
        finish_reason=finish_reason,
    )


def _normalize_stop_reason(stop_reason: Any) -> str | None:
    """Map Anthropic stop_reason to a normalized lowercase string."""
    if stop_reason is None:
        return None
    reason = str(stop_reason).lower()

    mapping: dict[str, str] = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "max_tokens",
        "tool_use": "tool_calls",
    }
    return mapping.get(reason, reason)


def _append_message(messages: list[dict[str, Any]], msg: dict[str, Any]) -> None:
    """Append *msg*, merging into the previous message when roles match.

    Anthropic requires strict user/assistant alternation.  When consecutive
    messages share a role (e.g. a tool_result user message followed by the
    current prompt user message, or two assistant turns in history) we merge
    their content blocks into a single message.
    """
    if messages and messages[-1]["role"] == msg["role"]:
        prev = messages[-1]
        prev_content = prev["content"]
        new_content = msg["content"]
        # Normalize both sides to list-of-blocks for merging.
        if isinstance(prev_content, str):
            prev_content = [{"type": "text", "text": prev_content}]
        if isinstance(new_content, str):
            new_content = [{"type": "text", "text": new_content}]
        prev["content"] = prev_content + new_content
    else:
        messages.append(msg)


def _normalize_input_part(part: Any) -> dict[str, Any] | None:
    """Convert Pollux parts into Anthropic content blocks."""
    if isinstance(part, str):
        return {"type": "text", "text": part}

    if not isinstance(part, dict):
        return None

    uri = part.get("uri")
    mime_type = part.get("mime_type")
    if not isinstance(uri, str) or not isinstance(mime_type, str):
        return None

    # Image URL support.
    if mime_type.startswith("image/"):
        return {
            "type": "image",
            "source": {
                "type": "url",
                "url": uri,
            },
        }

    # PDF support via document blocks.
    if mime_type == "application/pdf":
        return {
            "type": "document",
            "source": {
                "type": "url",
                "url": uri,
            },
        }

    raise APIError(
        f"Unsupported mime type for Anthropic provider: {mime_type}",
        hint="Anthropic supports images and PDFs via URL.",
    )
