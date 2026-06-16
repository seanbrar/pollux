"""Local Chat Completions provider for self-hosted inference servers.

Pollux targets the OpenAI Chat Completions wire format here, not a specific
inference engine. The supported surface is text or tool calls in, text or JSON
out: model-native reasoning text is surfaced when returned, and tool calling is
sent through the standard ``tools``/``tool_choice`` fields so a local server can
drive an agent loop. Reasoning controls, file uploads, context caching, and
deferred delivery stay unsupported — those belong to cloud providers, inference
servers, or application code, not to Pollux's orchestration layer.

Tool support trusts the server the same way JSON mode does: Pollux sends the
declarations and replays tool turns, and a server that ignores ``tools`` simply
never emits tool calls. There is no per-model capability probe (local servers
vary too much to query reliably).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
from typing import TYPE_CHECKING, Any, cast

import httpx

from pollux.errors import APIError, ConfigurationError, walk_exception_chain
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
    parse_chat_stream_chunk,
    parse_sse_line,
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
    ProviderStreamChunk,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from pollux.config import Config
    from pollux.interaction.environment import EnvironmentSnapshot
    from pollux.interaction.input import Input
    from pollux.interaction.requirements import OutputRequirements

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
            file_rejection_hint=(
                "Pass file content as text via Source.from_text(). "
                "Images, PDFs, and remote URIs are not supported."
            ),
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

    async def validate_request(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,  # noqa: ARG002
    ) -> None:
        """Fail fast on features the local provider does not support."""
        if requirements.reasoning_budget_tokens is not None:
            raise ConfigurationError(
                "Local provider does not support reasoning_budget_tokens",
                hint="Remove reasoning_budget_tokens.",
            )
        if requirements.reasoning_effort is not None:
            raise ConfigurationError(
                "Local provider does not support reasoning_effort controls",
                hint=(
                    "Local can surface model-native reasoning when the server "
                    "returns it, but Pollux does not send portable local "
                    "reasoning controls. Remove reasoning_effort."
                ),
            )
        for part in _compile.request_parts(snapshot, input):
            if not _is_text_part(part):
                raise ConfigurationError(
                    "Local provider does not support file or multimodal input",
                    hint=(
                        "Pass file content as text via Source.from_text(). "
                        "Images, PDFs, and remote URIs are not supported."
                    ),
                )

    def _build_payload(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Build the Chat Completions request body and the response schema, if any.

        Shared by ``generate`` and ``stream_generate``; the streaming path adds
        only the ``stream`` flags on top of this body.
        """
        history, _previous_response_id, _provider_state = _compile.prior_turns(input)
        response_schema = requirements.output_schema_json()
        tools = _compile.tool_dicts(snapshot)
        messages = _build_messages(
            _compile.request_parts(snapshot, input),
            history or None,
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
        if response_schema is not None:
            strict_schema = to_strict_schema(response_schema)
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
        merge_provider_options(
            payload,
            requirements.provider_options_for("local"),
            provider="local",
        )
        return payload, response_schema

    async def generate(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> ProviderResponse:
        """Generate a response via OpenAI-compatible Chat Completions."""
        await self.validate_request(snapshot, input, requirements, config)

        payload, response_schema = self._build_payload(
            snapshot, input, requirements, config
        )

        client = self._get_client()
        try:
            response = await client.post("chat/completions", json=payload)
            if response.is_error:
                raise httpx.HTTPStatusError(
                    extract_error_message(response),
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

        return _parse_response(data, response_schema=response_schema)

    async def stream_generate(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> AsyncIterator[ProviderStreamChunk]:
        """Stream normalized deltas via OpenAI-compatible Chat Completions."""
        await self.validate_request(snapshot, input, requirements, config)

        payload, _response_schema = self._build_payload(
            snapshot, input, requirements, config
        )
        payload["stream"] = True
        # Ask for a terminal usage chunk; servers that ignore it simply omit one.
        payload["stream_options"] = {"include_usage": True}

        client = self._get_client()
        try:
            async with client.stream(
                "POST", "chat/completions", json=payload
            ) as response:
                if response.is_error:
                    await response.aread()
                    raise httpx.HTTPStatusError(
                        extract_error_message(response),
                        request=response.request,
                        response=response,
                    )
                async for line in response.aiter_lines():
                    data = parse_sse_line(line)
                    if data is None:
                        continue
                    chunk = parse_chat_stream_chunk(data)
                    if chunk is not None:
                        yield chunk
        except asyncio.CancelledError:
            raise
        except (ConfigurationError, APIError):
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="local",
                phase="stream",
                allow_network_errors=True,
                message="Local provider stream failed",
                hint=_hint_for_local_error(e, base_url=self._base_url),
            ) from e

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

    Tool turns replay as the standard ``tool``-role result message and assistant
    ``tool_calls`` array; empty assistant turns carrying neither text nor a tool
    call are dropped so the transcript stays well-formed.
    """
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

    if item.role == "assistant" and not item.content and not tool_calls:
        return None

    return message


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
    choice, message = first_choice_message(data)

    text = extract_message_text(message.get("content"))
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

    tool_calls = parse_tool_calls(message.get("tool_calls"))

    return ProviderResponse(
        text=text,
        usage=parse_usage(data.get("usage")),
        reasoning=reasoning,
        structured=structured,
        tool_calls=tool_calls or None,
        response_id=extract_response_id(data),
        finish_reason=extract_finish_reason(choice),
    )


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


def _local_api_error(
    message: str,
    *,
    phase: str,
    hint: str | None = None,
) -> APIError:
    """Return a local-attributed APIError for direct boundary failures."""
    return APIError(message, hint=hint, provider="local", phase=phase)
