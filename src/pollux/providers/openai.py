"""OpenAI provider implementation."""

from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
import json
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse

from pollux.errors import APIError
from pollux.providers._errors import wrap_provider_error
from pollux.providers.base import ProviderCapabilities

if TYPE_CHECKING:
    from pathlib import Path


class OpenAIProvider:
    """OpenAI Responses API provider."""

    def __init__(self, api_key: str) -> None:
        """Initialize with an API key."""
        self.api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazily initialize and return the OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                raise APIError(
                    "openai package not installed",
                    hint="uv pip install openai",
                ) from e
            self._client = AsyncOpenAI(api_key=self.api_key)
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
            uploads=True,
            structured_outputs=True,
            reasoning=True,
            deferred_delivery=False,
            conversation=True,
        )

    async def generate(
        self,
        *,
        model: str,
        parts: list[Any],
        system_instruction: str | None = None,
        cache_name: str | None = None,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Literal["auto", "required", "none"] | dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        history: list[dict[str, Any]] | None = None,
        delivery_mode: str = "realtime",
        previous_response_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate a response using OpenAI's responses endpoint."""
        _ = cache_name, delivery_mode
        client = self._get_client()

        user_content: list[dict[str, str]] = []
        for part in parts:
            normalized = _normalize_input_part(part)
            if normalized is not None:
                user_content.append(normalized)

        if not user_content:
            user_content.append({"type": "input_text", "text": ""})

        input_messages: list[dict[str, Any]] = []
        history_items = history
        if previous_response_id and history_items is not None:
            # With previous_response_id, avoid replaying full transcript. Only pass
            # incremental tool outputs that must be provided explicitly.
            history_items = [
                item
                for item in history_items
                if isinstance(item, dict) and item.get("role") == "tool"
            ]
        if history_items is not None:
            for item in history_items:
                role = item.get("role")
                if not isinstance(role, str):
                    continue

                # Tool result message → function_call_output
                if role == "tool":
                    call_id = item.get("tool_call_id")
                    if not isinstance(call_id, str) or not call_id:
                        continue
                    content = item.get("content", "")
                    input_messages.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": content
                            if isinstance(content, str)
                            else str(content or ""),
                        }
                    )
                    continue

                # Assistant message with tool_calls → function_call items
                item_tool_calls = item.get("tool_calls")
                if role == "assistant" and isinstance(item_tool_calls, list):
                    for tc in item_tool_calls:
                        if not isinstance(tc, dict):
                            continue
                        call_id = tc.get("id")
                        name = tc.get("name")
                        if not isinstance(call_id, str) or not isinstance(name, str):
                            continue
                        arguments = tc.get("arguments", "")
                        if not isinstance(arguments, str):
                            arguments = str(arguments or "")
                        input_messages.append(
                            {
                                "type": "function_call",
                                "call_id": call_id,
                                "name": name,
                                "arguments": arguments,
                            }
                        )

                # Regular user/assistant text message
                content = item.get("content")
                if not isinstance(content, str):
                    continue
                input_messages.append(
                    {
                        "role": role,
                        "content": [{"type": "input_text", "text": content}],
                    }
                )
        input_messages.append({"role": "user", "content": user_content})

        create_kwargs: dict[str, Any] = {
            "model": model,
            "input": input_messages,
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature
        if top_p is not None:
            create_kwargs["top_p"] = top_p

        if tools is not None:
            create_kwargs["tools"] = []
            for t in tools:
                if "name" in t:
                    tool_def: dict[str, Any] = {
                        "type": "function",
                        "name": t["name"],
                    }
                    if "description" in t:
                        tool_def["description"] = t["description"]
                    if "parameters" in t:
                        tool_def["parameters"] = t["parameters"]
                    if "strict" in t:
                        tool_def["strict"] = t["strict"]
                    else:
                        tool_def["strict"] = True
                    create_kwargs["tools"].append(tool_def)
            if tool_choice is not None:
                if isinstance(tool_choice, str):
                    create_kwargs["tool_choice"] = tool_choice
                elif isinstance(tool_choice, dict) and "name" in tool_choice:
                    create_kwargs["tool_choice"] = {
                        "type": "function",
                        "name": tool_choice["name"],
                    }
        if system_instruction:
            create_kwargs["instructions"] = system_instruction
        if previous_response_id:
            create_kwargs["previous_response_id"] = previous_response_id
        if reasoning_effort is not None:
            create_kwargs["reasoning"] = {
                "effort": reasoning_effort,
                "summary": "auto",
            }
        if response_schema is not None:
            strict_schema = _to_openai_strict_schema(response_schema)
            create_kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "pollux_structured_output",
                    "schema": strict_schema,
                    "strict": True,
                }
            }

        try:
            response = await client.responses.create(**create_kwargs)
            text = getattr(response, "output_text", "") or ""
            response_id = getattr(response, "id", None)
            structured: Any = None
            if response_schema is not None and text:
                try:
                    structured = json.loads(text)
                except Exception:
                    structured = None
            usage_raw = getattr(response, "usage", None)
            usage: dict[str, int] = {}
            if usage_raw is not None:
                usage = {
                    "input_tokens": int(getattr(usage_raw, "input_tokens", 0)),
                    "output_tokens": int(getattr(usage_raw, "output_tokens", 0)),
                    "total_tokens": int(getattr(usage_raw, "total_tokens", 0)),
                }
                out_details = getattr(usage_raw, "output_tokens_details", None)
                if out_details:
                    reasoning_toks = getattr(out_details, "reasoning_tokens", None)
                    if reasoning_toks is not None:
                        usage["reasoning_tokens"] = int(reasoning_toks)

            tool_calls = []
            reasoning_parts: list[str] = []
            for item in getattr(response, "output", []):
                item_type = getattr(item, "type", None)
                if item_type == "function_call":
                    tool_calls.append(
                        {
                            "id": getattr(item, "call_id", None),
                            "name": getattr(item, "name", None),
                            "arguments": getattr(item, "arguments", None),
                        }
                    )
                elif item_type == "reasoning":
                    for summary_item in getattr(item, "summary", None) or []:
                        summary_text = getattr(summary_item, "text", None)
                        if summary_text:
                            reasoning_parts.append(summary_text)

            payload: dict[str, Any] = {"text": text, "usage": usage}
            if structured is not None:
                payload["structured"] = structured
            if isinstance(response_id, str):
                payload["response_id"] = response_id
            if tool_calls:
                payload["tool_calls"] = tool_calls
            if reasoning_parts:
                payload["reasoning"] = "\n\n".join(reasoning_parts).strip()
            return payload
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="openai",
                phase="generate",
                allow_network_errors=True,
                message="OpenAI generate failed",
            ) from e

    async def upload_file(self, path: Path, mime_type: str) -> str:
        """Upload a local file and return a URI-like identifier."""
        client = self._get_client()

        try:
            if _is_text_like_mime_type(mime_type):
                # Files API rejects plain text uploads; inline as input_text payload.
                text = path.read_text(encoding="utf-8")
                encoded = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")
                return f"openai://text/{encoded}"

            result = await client.files.create(
                file=path,
                purpose="user_data",
                expires_after={"anchor": "created_at", "seconds": 86_400},
            )

            file_id = getattr(result, "id", None)
            if not isinstance(file_id, str):
                raise APIError("OpenAI upload did not return a file id")
            return f"openai://file/{file_id}"
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="openai",
                phase="upload",
                allow_network_errors=False,
                message="OpenAI upload failed",
            ) from e

    async def create_cache(
        self,
        *,
        model: str,
        parts: list[Any],
        system_instruction: str | None = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """Raise because OpenAI context caching is not supported."""
        _ = model, parts, system_instruction, ttl_seconds
        raise APIError("OpenAI provider does not support context caching")

    async def aclose(self) -> None:
        """Close underlying async client resources."""
        client = self._client
        if client is None:
            return
        self._client = None
        await client.close()


def _to_openai_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize a JSON schema for OpenAI strict structured-output requirements."""
    normalized = deepcopy(schema)

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node

        updated: dict[str, Any] = {}
        for key, value in node.items():
            updated[key] = walk(value)

        if updated.get("type") == "object" or "properties" in updated:
            properties = updated.get("properties", {})
            if isinstance(properties, dict):
                updated["additionalProperties"] = False
                if "required" not in updated:
                    updated["required"] = list(properties.keys())

        return updated

    result = walk(normalized)
    if not isinstance(result, dict):
        raise APIError("Invalid response_schema: expected object schema")
    return result


def _normalize_input_part(part: Any) -> dict[str, str] | None:
    """Convert Pollux parts into OpenAI Responses API content parts."""
    if isinstance(part, str):
        return {"type": "input_text", "text": part}

    if not isinstance(part, dict):
        return None

    uri = part.get("uri")
    mime_type = part.get("mime_type")
    if not isinstance(uri, str) or not isinstance(mime_type, str):
        return None

    uploaded_prefix = "openai://file/"
    inline_text_prefix = "openai://text/"
    if uri.startswith(inline_text_prefix):
        encoded_text = uri.removeprefix(inline_text_prefix)
        if not encoded_text:
            raise APIError("Invalid OpenAI text URI: missing content payload")
        try:
            text = base64.urlsafe_b64decode(encoded_text.encode("ascii")).decode(
                "utf-8"
            )
        except Exception as e:
            raise APIError("Invalid OpenAI text URI: malformed content payload") from e
        return {"type": "input_text", "text": text}

    if uri.startswith(uploaded_prefix):
        file_id = uri.removeprefix(uploaded_prefix)
        if not file_id:
            raise APIError("Invalid OpenAI file URI: missing file id")
        if mime_type.startswith("image/"):
            return {"type": "input_image", "file_id": file_id}
        return {"type": "input_file", "file_id": file_id}

    parsed = urlparse(uri)
    if parsed.scheme not in {"http", "https"}:
        raise APIError(f"Unsupported URI for OpenAI provider: {uri}")

    if mime_type == "application/pdf":
        return {"type": "input_file", "file_url": uri}
    if mime_type.startswith("image/"):
        return {"type": "input_image", "image_url": uri}

    raise APIError(
        f"Unsupported remote mime type for OpenAI provider: {mime_type}",
        hint="Supported remote types for v1.0 are PDFs and images.",
    )


def _is_text_like_mime_type(mime_type: str) -> bool:
    """Return True when a MIME type should be inlined as input_text."""
    if mime_type.startswith("text/"):
        return True

    common_text_like = {
        "application/csv",
        "application/json",
        "application/xml",
        "application/yaml",
        "application/x-yaml",
        "application/x-tex",
        "application/x-latex",
        "application/x-bibtex",
        "application/javascript",
        "application/x-javascript",
    }
    if mime_type in common_text_like:
        return True

    return mime_type.endswith(("+json", "+xml"))
