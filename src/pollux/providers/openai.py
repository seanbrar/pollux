"""OpenAI provider implementation."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from pollux.errors import APIError
from pollux.providers._errors import wrap_provider_error
from pollux.providers._utils import to_strict_schema
from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import ProviderRequest, ProviderResponse, ToolCall

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
        request: ProviderRequest,
    ) -> ProviderResponse:
        """Generate a response using OpenAI's responses endpoint."""
        model = request.model
        parts = request.parts
        system_instruction = request.system_instruction
        cache_name = request.cache_name
        response_schema = request.response_schema
        temperature = request.temperature
        top_p = request.top_p
        tools = request.tools
        tool_choice = request.tool_choice
        reasoning_effort = request.reasoning_effort
        history = request.history
        previous_response_id = request.previous_response_id

        _ = cache_name
        client = self._get_client()

        user_content: list[dict[str, str]] = []
        for part in parts:
            normalized = _normalize_input_part(part)
            if normalized is not None:
                user_content.append(normalized)

        has_real_content = False
        for c in user_content:
            if c.get("type") != "input_text" or c.get("text"):
                has_real_content = True
                break

        if not user_content:
            user_content.append({"type": "input_text", "text": ""})

        input_messages: list[dict[str, Any]] = []
        history_items = history
        if previous_response_id and history_items is not None:
            # With previous_response_id, avoid replaying full transcript. Keep
            # tool outputs *and* the assistant function_call entries they
            # reference — naked function_call_output items without a matching
            # function_call cause a 400 from the Responses API.
            history_items = [
                item
                for item in history_items
                if item.role == "tool" or (item.role == "assistant" and item.tool_calls)
            ]
        if history_items is not None:
            for item in history_items:
                role = item.role

                # Tool result message → function_call_output
                if role == "tool":
                    call_id = item.tool_call_id
                    if not call_id:
                        continue
                    input_messages.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": item.content,
                        }
                    )
                    continue

                # Assistant message with tool_calls → function_call items
                if role == "assistant" and item.tool_calls:
                    for tc in item.tool_calls:
                        input_messages.append(
                            {
                                "type": "function_call",
                                "call_id": tc.id,
                                "name": tc.name,
                                "arguments": tc.arguments,
                            }
                        )

                # Regular user/assistant text message
                if not item.content:
                    continue
                text_type = "output_text" if role == "assistant" else "input_text"
                input_messages.append(
                    {
                        "role": role,
                        "content": [{"type": text_type, "text": item.content}],
                    }
                )

        if has_real_content or not input_messages:
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
                    strict = t.get("strict", True)
                    if "parameters" in t:
                        params = t["parameters"]
                        if strict and isinstance(params, dict):
                            params = to_strict_schema(params)
                        tool_def["parameters"] = params
                    tool_def["strict"] = strict
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
            strict_schema = to_strict_schema(response_schema)
            create_kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "pollux_structured_output",
                    "schema": strict_schema,
                    "strict": True,
                }
            }

        response = await client.responses.create(**create_kwargs)
        text = getattr(response, "output_text", "") or ""
        response_id = getattr(response, "id", None)
        finish_reason = _extract_finish_reason(response)
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
            if item.type == "function_call":
                tool_calls.append(
                    ToolCall(
                        id=item.call_id,
                        name=item.name,
                        arguments=item.arguments or "{}",
                    )
                )
            elif item.type == "reasoning":
                for summary_item in item.summary or []:
                    if summary_item.text:
                        reasoning_parts.append(summary_item.text)

        return ProviderResponse(
            text=text,
            usage=usage,
            reasoning="\n\n".join(reasoning_parts).strip() if reasoning_parts else None,
            structured=structured,
            tool_calls=tool_calls if tool_calls else None,
            response_id=response_id if isinstance(response_id, str) else None,
            finish_reason=finish_reason,
        )

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

    async def delete_file(self, file_id: str) -> None:
        """Delete a previously uploaded file from OpenAI storage."""
        client = self._get_client()
        await client.files.delete(file_id)

    async def aclose(self) -> None:
        """Close underlying async client resources."""
        client = self._client
        if client is None:
            return
        self._client = None
        await client.close()


def _extract_finish_reason(response: Any) -> str | None:
    """Extract OpenAI finish reason, preferring incomplete_details.reason.

    The Responses API exposes ``response.status`` (a string like "completed" or
    "incomplete") and, when incomplete, an ``IncompleteDetails`` model with a
    ``.reason`` field ("max_output_tokens" or "content_filter").  We surface
    the specific reason when available so callers get the actionable root cause.
    """
    status = getattr(response, "status", None)
    if not isinstance(status, str):
        return None

    normalized_status = status.lower()
    if normalized_status == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) if details is not None else None
        if isinstance(reason, str) and reason:
            return reason.lower()

    return normalized_status


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
