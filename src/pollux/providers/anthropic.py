"""Anthropic Messages API provider."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from pollux.errors import APIError
from pollux.providers._errors import wrap_provider_error
from pollux.providers._utils import to_strict_schema
from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import Message, ProviderRequest, ProviderResponse, ToolCall

if TYPE_CHECKING:
    from pathlib import Path

_ANTHROPIC_MAX_TOKENS = 8192
_INTERLEAVED_THINKING_BETA_HEADER = "interleaved-thinking-2025-05-14"
_ANTHROPIC_THINKING_BLOCKS_KEY = "anthropic_thinking_blocks"
_ALLOWED_REASONING_EFFORTS = {"low", "medium", "high", "max"}
_ADAPTIVE_THINKING_MODEL_PREFIXES = ("claude-opus-4-6",)
_MANUAL_THINKING_BUDGETS = {
    "low": 2048,
    "medium": 4096,
    "high": 6144,
    "max": 7168,
}


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
            reasoning=True,
            deferred_delivery=False,
            conversation=True,
        )

    @staticmethod
    def _normalize_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert tool dicts to Anthropic format (parameters → input_schema)."""
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
        return anthropic_tools

    @staticmethod
    def _map_tool_choice(
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, str] | None:
        """Map tool_choice to Anthropic format."""
        if tool_choice is None:
            return None
        if isinstance(tool_choice, str):
            if tool_choice == "required":
                return {"type": "any"}
            if tool_choice in ("auto", "none"):
                return {"type": tool_choice}
        elif isinstance(tool_choice, dict) and "name" in tool_choice:
            return {"type": "tool", "name": tool_choice["name"]}
        return None

    @staticmethod
    def _build_messages(
        parts: list[Any],
        history: list[Message] | None,
        provider_state: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Build the messages list from history + current parts.

        Anthropic requires strict user/assistant role alternation, so
        consecutive same-role messages are merged via ``_append_message``.
        """
        messages: list[dict[str, Any]] = []

        if history:
            for idx, item in enumerate(history):
                item_provider_state = _get_history_item_provider_state(
                    provider_state, idx
                )
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
                    thinking_blocks = _extract_thinking_blocks_for_replay(
                        item_provider_state
                    )
                    if item.content:
                        content_blocks.append(
                            {
                                "type": "text",
                                "text": item.content,
                            }
                        )
                    if item.tool_calls:
                        content_blocks.extend(thinking_blocks)
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
                    elif thinking_blocks:
                        content_blocks.extend(thinking_blocks)
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

        return messages

    async def generate(
        self,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """Generate a response using Anthropic's Messages API."""
        client = self._get_client()

        # No Anthropic equivalents or deferred features.
        _ = request.cache_name
        _ = request.previous_response_id

        messages = self._build_messages(
            request.parts,
            request.history,
            request.provider_state,
        )

        # Build create kwargs.
        create_kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
        }

        if request.system_instruction:
            create_kwargs["system"] = request.system_instruction
        if request.temperature is not None:
            create_kwargs["temperature"] = request.temperature
        if request.top_p is not None:
            create_kwargs["top_p"] = request.top_p

        # Tool definitions.
        if request.tools is not None:
            anthropic_tools = self._normalize_tools(request.tools)
            if anthropic_tools:
                create_kwargs["tools"] = anthropic_tools

            mapped = self._map_tool_choice(request.tool_choice)
            if mapped is not None:
                create_kwargs["tool_choice"] = mapped

        output_config: dict[str, Any] = {}

        # Structured output via output_config.format.
        if request.response_schema is not None:
            strict_schema = to_strict_schema(request.response_schema)
            output_config["format"] = {
                "type": "json_schema",
                "schema": strict_schema,
            }

        if request.reasoning_effort is not None:
            effort = _normalize_reasoning_effort(request.reasoning_effort)
            output_config["effort"] = effort
            if _supports_adaptive_thinking(request.model):
                create_kwargs["thinking"] = {"type": "adaptive"}
            else:
                create_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": _MANUAL_THINKING_BUDGETS[effort],
                }
            if request.tools:
                create_kwargs["extra_headers"] = {
                    "anthropic-beta": _INTERLEAVED_THINKING_BETA_HEADER
                }

        if output_config:
            create_kwargs["output_config"] = output_config

        try:
            response = await client.messages.create(**create_kwargs)
            return _parse_response(response, response_schema=request.response_schema)
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
    reasoning_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    thinking_blocks: list[dict[str, str]] = []

    for block in getattr(response, "content", []):
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_parts.append(getattr(block, "text", ""))
        elif block_type == "thinking":
            thinking = getattr(block, "thinking", "")
            signature = getattr(block, "signature", None)
            if isinstance(thinking, str) and thinking:
                reasoning_parts.append(thinking)
            if isinstance(thinking, str) and isinstance(signature, str):
                thinking_blocks.append(
                    {
                        "type": "thinking",
                        "thinking": thinking,
                        "signature": signature,
                    }
                )
        elif block_type == "redacted_thinking":
            data = getattr(block, "data", None)
            if isinstance(data, str):
                thinking_blocks.append({"type": "redacted_thinking", "data": data})
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
        reasoning="\n\n".join(reasoning_parts).strip() if reasoning_parts else None,
        structured=structured,
        tool_calls=tool_calls if tool_calls else None,
        response_id=response_id if isinstance(response_id, str) else None,
        finish_reason=finish_reason,
        provider_state=(
            {_ANTHROPIC_THINKING_BLOCKS_KEY: thinking_blocks}
            if thinking_blocks
            else None
        ),
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


def _normalize_reasoning_effort(reasoning_effort: str) -> str:
    """Normalize and validate Anthropic effort values."""
    effort = reasoning_effort.strip().lower()
    if effort not in _ALLOWED_REASONING_EFFORTS:
        allowed = ", ".join(sorted(_ALLOWED_REASONING_EFFORTS))
        raise APIError(
            f"Unsupported reasoning_effort for Anthropic: {reasoning_effort!r}",
            hint=f"Use one of: {allowed}.",
        )
    return effort


def _supports_adaptive_thinking(model: str) -> bool:
    """Whether this model should use thinking.type='adaptive'."""
    model_name = model.lower()
    return any(
        model_name.startswith(prefix) for prefix in _ADAPTIVE_THINKING_MODEL_PREFIXES
    )


def _get_history_item_provider_state(
    provider_state: dict[str, Any] | None, index: int
) -> dict[str, Any] | None:
    """Return provider_state for a specific history item."""
    if provider_state is None:
        return None
    history_states = provider_state.get("history")
    if (
        not isinstance(history_states, list)
        or index < 0
        or index >= len(history_states)
    ):
        return None
    item_state = history_states[index]
    return item_state if isinstance(item_state, dict) else None


def _extract_thinking_blocks_for_replay(
    item_provider_state: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """Extract sanitized thinking blocks to replay in Anthropic tool loops."""
    if item_provider_state is None:
        return []
    raw_blocks = item_provider_state.get(_ANTHROPIC_THINKING_BLOCKS_KEY)
    if not isinstance(raw_blocks, list):
        return []

    blocks: list[dict[str, str]] = []
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            continue
        block_type = raw.get("type")
        if block_type == "thinking":
            thinking = raw.get("thinking")
            signature = raw.get("signature")
            if isinstance(thinking, str) and isinstance(signature, str):
                blocks.append(
                    {
                        "type": "thinking",
                        "thinking": thinking,
                        "signature": signature,
                    }
                )
        elif block_type == "redacted_thinking":
            data = raw.get("data")
            if isinstance(data, str):
                blocks.append({"type": "redacted_thinking", "data": data})
    return blocks


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
