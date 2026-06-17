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
import base64
from collections.abc import Mapping
import json
from typing import TYPE_CHECKING, Any, cast

import httpx

from pollux.errors import (
    APIError,
    ConfigurationError,
    ToolCallParseError,
    walk_exception_chain,
)
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

_DEFAULT_LOCAL_TIMEOUT_S = 300.0


class LocalProvider:
    """Chat Completions provider for self-hosted OpenAI-compatible servers."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        timeout_s: float = _DEFAULT_LOCAL_TIMEOUT_S,
    ) -> None:
        """Initialize with the server's base URL and an optional auth token.

        Most local servers ignore the Authorization header; some require
        *any* value. We default to the literal ``"local"`` so both cases
        behave the same.
        """
        self._base_url = base_url
        self._api_key = api_key or "local"
        self._timeout_s = timeout_s
        self._client: Any = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Return supported feature flags (narrow by design)."""
        return ProviderCapabilities(
            persistent_cache=False,
            uploads=True,
            structured_outputs=True,
            reasoning=False,
            reasoning_budget_tokens=False,
            deferred_delivery=False,
            conversation=True,
            implicit_caching=False,
            file_rejection_hint=(
                "Local supports text, image, and audio inputs through "
                "OpenAI-compatible Chat Completions content parts."
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
                timeout=self._timeout_s,
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
            if not _is_supported_local_part(part):
                raise ConfigurationError(
                    "Local provider does not support this input MIME type",
                    hint=(
                        "Local supports text, image, and audio inputs. "
                        "Use a provider with broader multimodal support for "
                        "PDF, video, or arbitrary binary files."
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
        payload: dict[str, Any] = {"messages": messages}
        if config.model is not None:
            payload["model"] = config.model
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
                _raise_tool_call_parse_error_if_present(
                    extract_error_message(response),
                    phase="generate",
                    tools_present="tools" in payload,
                )
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
                    _raise_tool_call_parse_error_if_present(
                        extract_error_message(response),
                        phase="stream",
                        tools_present="tools" in payload,
                    )
                    raise httpx.HTTPStatusError(
                        extract_error_message(response),
                        request=response.request,
                        response=response,
                    )
                async for line in response.aiter_lines():
                    data = parse_sse_line(line)
                    if data is None:
                        continue
                    _raise_sse_error_if_present(data, tools_present="tools" in payload)
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
        """Inline local files for OpenAI-compatible Chat Completions."""
        try:
            data = path.read_bytes()
        except Exception as exc:
            raise _local_api_error(
                f"Failed to read local file for inline input: {path}",
                phase="upload",
            ) from exc

        if _is_text_like_mime_type(mime_type):
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ConfigurationError(
                    f"Local text input is not valid UTF-8: {path}",
                    hint="Use a valid UTF-8 text file or pass a binary media type.",
                ) from exc
            return ProviderFileAsset(
                file_id=text,
                provider="local",
                mime_type=mime_type,
                file_name=path.name,
                is_inline_fallback=True,
            )

        if mime_type.startswith(("image/", "audio/")):
            return ProviderFileAsset(
                file_id=_to_data_url(data, mime_type),
                provider="local",
                mime_type=mime_type,
                file_name=path.name,
            )

        raise ConfigurationError(
            f"Unsupported local input MIME type: {mime_type}",
            hint="Local supports text, image, and audio files.",
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


def _is_supported_local_part(part: Any) -> bool:
    """Return True when *part* can become local Chat Completions content."""
    if part is None:
        return True
    if isinstance(part, str):
        return True
    if isinstance(part, ProviderFileAsset):
        return part.provider == "local" and (
            part.is_inline_fallback or part.mime_type.startswith(("image/", "audio/"))
        )
    if isinstance(part, Mapping):
        mime_type = part.get("mime_type")
        if "file_path" in part:
            return isinstance(mime_type, str) and (
                _is_text_like_mime_type(mime_type)
                or mime_type.startswith(("image/", "audio/"))
            )
        if "uri" in part or "mime_type" in part:
            uri = part.get("uri")
            return (
                isinstance(uri, str)
                and isinstance(mime_type, str)
                and (
                    mime_type.startswith("image/")
                    or (
                        mime_type.startswith("audio/") and uri.startswith("data:audio/")
                    )
                )
            )
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

    user_content = _content_from_parts(parts)
    if user_content or not messages:
        messages.append({"role": "user", "content": user_content})

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


def _content_from_parts(parts: list[Any]) -> str | list[dict[str, Any]]:
    """Convert Pollux parts into local Chat Completions message content."""
    content_parts: list[dict[str, Any]] = []
    for part in parts:
        normalized = _normalize_input_part(part)
        if normalized is not None:
            content_parts.append(normalized)
    if not content_parts:
        return ""
    if all(part.get("type") == "text" for part in content_parts):
        return "\n\n".join(cast("str", part["text"]) for part in content_parts)
    return content_parts


def _normalize_input_part(part: Any) -> dict[str, Any] | None:
    """Convert one Pollux part into a local Chat Completions content item."""
    if part is None:
        return None
    if isinstance(part, str):
        return {"type": "text", "text": part}
    if isinstance(part, Mapping) and isinstance(part.get("text"), str):
        return {"type": "text", "text": cast("str", part["text"])}

    if isinstance(part, ProviderFileAsset):
        if part.provider != "local":
            raise _local_api_error(
                f"Local provider cannot use {part.provider} file assets.",
                phase="generate",
            )
        if part.is_inline_fallback:
            return {"type": "text", "text": part.file_id}
        return _media_content_part(
            uri=part.file_id,
            mime_type=part.mime_type,
            file_name=part.file_name,
        )

    if isinstance(part, Mapping):
        uri = part.get("uri")
        mime_type = part.get("mime_type")
        if isinstance(uri, str) and isinstance(mime_type, str):
            return _media_content_part(uri=uri, mime_type=mime_type)

    raise ConfigurationError(
        f"Unsupported local input part: {type(part).__name__}",
        hint="Local supports text, image, and audio inputs.",
    )


def _media_content_part(
    *, uri: str, mime_type: str, file_name: str | None = None
) -> dict[str, Any]:
    """Build an OpenAI-compatible media content item for local servers."""
    _ = file_name
    if mime_type.startswith("image/"):
        return {"type": "image_url", "image_url": {"url": uri}}
    if mime_type.startswith("audio/"):
        data, audio_format = _audio_payload(uri=uri, mime_type=mime_type)
        return {
            "type": "input_audio",
            "input_audio": {"data": data, "format": audio_format},
        }
    raise ConfigurationError(
        f"Unsupported local input MIME type: {mime_type}",
        hint="Local supports text, image, and audio inputs.",
    )


def _audio_payload(*, uri: str, mime_type: str) -> tuple[str, str]:
    """Return base64 audio payload and format for Chat Completions."""
    if not uri.startswith("data:"):
        raise ConfigurationError(
            "Local audio input requires a data URL",
            hint="Use Source.from_file(...) for local audio files.",
        )
    marker = ";base64,"
    if marker not in uri:
        raise ConfigurationError(
            "Local audio data URL must be base64 encoded",
            hint="Use Source.from_file(...) for local audio files.",
        )
    data = uri.split(marker, 1)[1]
    return data, _audio_format(mime_type)


def _audio_format(mime_type: str) -> str:
    """Return the Chat Completions audio format token for a MIME type."""
    suffix = mime_type.split("/", 1)[1].split(";", 1)[0].lower()
    if suffix in {"mpeg", "mpga"}:
        return "mp3"
    return suffix


def _is_text_like_mime_type(mime_type: str) -> bool:
    """Return True when local should inline file bytes as text."""
    if mime_type.startswith("text/"):
        return True
    return mime_type in {
        "application/json",
        "application/xml",
        "application/yaml",
        "application/x-yaml",
    } or mime_type.endswith(("+json", "+xml"))


def _to_data_url(data: bytes, mime_type: str) -> str:
    """Encode raw file bytes as a base64 data URL."""
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _parse_response(
    data: Mapping[str, Any],
    *,
    response_schema: dict[str, Any] | None,
) -> ProviderResponse:
    """Parse a Chat Completions payload into ProviderResponse.

    JSON parsing is opportunistic: a non-JSON response despite JSON mode
    produces ``structured=None`` (matching OpenRouter) rather than raising,
    because local servers vary in their JSON-mode fidelity. A ``None``
    structured facet is Pollux's signal that no structured output was produced.
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


def _raise_sse_error_if_present(
    data: Mapping[str, Any], *, tools_present: bool
) -> None:
    """Raise when a streaming payload is an OpenAI-compatible error envelope."""
    error = data.get("error")
    if error is None:
        return
    message = _error_message_from_payload(error)
    _raise_tool_call_parse_error_if_present(
        message, phase="stream", tools_present=tools_present
    )
    raise _local_api_error(
        f"Local provider stream failed: {message}",
        phase="stream",
    )


def _error_message_from_payload(payload: Any) -> str:
    """Extract a compact message from a streamed error payload."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, Mapping):
        message = payload.get("message")
        if isinstance(message, str) and message:
            return message
        code = payload.get("code")
        if isinstance(code, str) and code:
            return code
    return "Local provider stream returned an error payload."


def _raise_tool_call_parse_error_if_present(
    message: str, *, phase: str, tools_present: bool
) -> None:
    """Classify local tool-call JSON parser failures as recoverable tool errors."""
    if not _is_tool_call_parse_failure(message, tools_present=tools_present):
        return
    raise ToolCallParseError(
        "Local provider rejected a tool-call JSON payload",
        hint=message,
        provider="local",
        phase=phase,
    )


def _is_tool_call_parse_failure(message: str, *, tools_present: bool) -> bool:
    """Return True for common local-server tool-call parser failures."""
    msg = message.lower()
    mentions_tooling = any(
        marker in msg
        for marker in (
            "tool call",
            "tool-call",
            "tool_calls",
            "function call",
            "function_call",
        )
    )
    mentions_json_parse = any(
        marker in msg
        for marker in (
            "json",
            "parse",
            "parsed",
            "parser",
            "invalid",
            "arguments",
            "schema",
        )
    )
    return mentions_json_parse and (mentions_tooling or tools_present)


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
                "Local inference timed out. Increase Config.request_timeout_s "
                "or reduce input size."
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
