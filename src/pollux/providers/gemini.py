"""Gemini provider implementation."""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any, Literal

from pollux.errors import APIError
from pollux.providers._errors import wrap_provider_error
from pollux.providers.base import ProviderCapabilities

if TYPE_CHECKING:
    from pathlib import Path


class GeminiProvider:
    """Google Gemini API provider."""

    def __init__(self, api_key: str) -> None:
        """Create provider with an API key."""
        self.api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-initialize the Gemini client."""
        if self._client is None:
            try:
                from google import genai
            except ImportError as e:
                raise APIError(
                    "google-genai package not installed",
                    hint="uv pip install google-genai",
                ) from e

            # Initialize with just API key as per 'Gemini Developer API' instructions.
            # If user wanted Vertex, they'd need to provide project/location logic,
            # but current impl only took api_key.
            self._client = genai.Client(api_key=self.api_key)
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
            caching=True,
            uploads=True,
            structured_outputs=True,
            reasoning=False,
            deferred_delivery=False,
            conversation=True,
        )

    def _convert_parts(self, parts: list[Any]) -> list[Any]:
        """Convert internal part representation to google-genai SDK types."""
        from google.genai import types

        converted: list[Any] = []
        for p in parts:
            if isinstance(p, str):
                converted.append(p)
            elif isinstance(p, dict):
                # Handle URI-based parts (after upload)
                if "uri" in p and "mime_type" in p:
                    converted.append(
                        types.Part(
                            file_data=types.FileData(
                                file_uri=p["uri"], mime_type=p["mime_type"]
                            )
                        )
                    )
                # Handle text parts in dict
                elif "text" in p:
                    converted.append(p["text"])
                else:
                    # Fallback for other dicts, though we should likely validate
                    converted.append(p)
            else:
                converted.append(p)
        return converted

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
        """Generate content using Gemini API."""
        _ = (
            reasoning_effort,
            delivery_mode,
            previous_response_id,
        )
        client = self._get_client()
        from google.genai import types

        config: dict[str, Any] = {}
        if system_instruction is not None:
            config["system_instruction"] = system_instruction
        if cache_name is not None:
            config["cached_content"] = cache_name
        if response_schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = response_schema
        if temperature is not None:
            config["temperature"] = temperature
        if top_p is not None:
            config["top_p"] = top_p

        if tools is not None:
            tool_objs = []
            for t in tools:
                if "name" in t:
                    tool_objs.append(
                        types.Tool(
                            function_declarations=[
                                types.FunctionDeclaration(
                                    name=t["name"],
                                    description=t.get("description", ""),
                                    parameters=t.get("parameters"),
                                )
                            ]
                        )
                    )
            if tool_objs:
                config["tools"] = tool_objs

            if isinstance(tool_choice, str):
                mode = tool_choice.upper()
                if mode in ("AUTO", "ANY", "NONE"):
                    config["tool_config"] = {"function_calling_config": {"mode": mode}}
                elif mode == "REQUIRED":
                    config["tool_config"] = {"function_calling_config": {"mode": "ANY"}}
            elif isinstance(tool_choice, dict) and "name" in tool_choice:
                # Force specific function
                config["tool_config"] = {
                    "function_calling_config": {
                        "mode": "ANY",
                        "allowed_function_names": [tool_choice["name"]],
                    }
                }

        input_contents = []
        call_id_to_name: dict[str, str] = {}

        if history:
            for item in history:
                role = item.get("role")
                if not isinstance(role, str):
                    continue

                if role == "tool":
                    call_id = item.get("tool_call_id")
                    name = call_id_to_name.get(call_id) if call_id else None
                    if not name:
                        name = call_id or "unknown_tool"

                    content = item.get("content", "")
                    if isinstance(content, str):
                        try:
                            parsed_content = json.loads(content)
                        except Exception:
                            parsed_content = {"result": content}
                    else:
                        parsed_content = content or {}

                    input_contents.append(
                        types.Content(
                            role="user",
                            parts=[
                                types.Part.from_function_response(
                                    name=name,
                                    response=parsed_content,
                                )
                            ],
                        )
                    )
                elif role == "assistant":
                    content_parts = []
                    content = item.get("content")
                    if isinstance(content, str) and content:
                        content_parts.append(types.Part.from_text(text=content))

                    tool_calls = item.get("tool_calls")
                    if isinstance(tool_calls, list):
                        for tc in tool_calls:
                            if not isinstance(tc, dict):
                                continue
                            call_id = tc.get("id")
                            name = tc.get("name")
                            if isinstance(call_id, str) and isinstance(name, str):
                                call_id_to_name[call_id] = name
                                args = tc.get("arguments", "")
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args) if args else {}
                                    except Exception:
                                        args = {}
                                elif not isinstance(args, dict):
                                    args = {}
                                content_parts.append(
                                    types.Part.from_function_call(
                                        name=name,
                                        args=args,
                                    )
                                )
                    if content_parts:
                        input_contents.append(
                            types.Content(role="model", parts=content_parts)
                        )
                elif role == "user":
                    content = item.get("content")
                    if isinstance(content, str) and content:
                        input_contents.append(
                            types.Content(
                                role="user", parts=[types.Part.from_text(text=content)]
                            )
                        )

        if not input_contents:
            # No history — use the original flat-parts path unchanged.
            contents: Any = self._convert_parts(parts)
        else:
            # History present — append current prompt as a Content object.
            user_parts: list[Any] = []
            for cp in self._convert_parts(parts):
                if isinstance(cp, str):
                    user_parts.append(types.Part.from_text(text=cp))
                else:
                    user_parts.append(cp)
            if user_parts:
                input_contents.append(types.Content(role="user", parts=user_parts))
            contents = input_contents

        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config or None,
            )
            return self._parse_response(response)
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="gemini",
                phase="generate",
                allow_network_errors=True,
                message="Gemini generate failed",
            ) from e

    async def _wait_for_file_active(
        self,
        file_name: str,
        *,
        timeout_seconds: float = 300.0,
        poll_interval: float = 2.0,
    ) -> Any:
        """Poll file status until it becomes ACTIVE or errors out."""
        client = self._get_client()
        deadline = time.monotonic() + timeout_seconds
        last_state = "STATE_UNSPECIFIED"

        while time.monotonic() < deadline:
            file_obj = await client.aio.files.get(name=file_name)
            state = self._file_state_name(file_obj)
            last_state = state

            if state == "ACTIVE":
                return file_obj
            if state == "FAILED":
                raise APIError(
                    f"File processing failed: {self._file_error_message(file_obj)}"
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(poll_interval, remaining))

        raise APIError(
            "File did not become active within "
            f"{timeout_seconds}s (stuck in {last_state})"
        )

    async def upload_file(self, path: Path, mime_type: str) -> str:
        """Upload a file to Gemini."""
        client = self._get_client()

        try:
            result = await client.aio.files.upload(
                file=path, config={"mime_type": mime_type}
            )

            file_name = getattr(result, "name", None)
            if not isinstance(file_name, str) or not file_name:
                raise APIError("Gemini upload did not return a file name")

            state = self._file_state_name(result)
            if state == "FAILED":
                raise APIError(
                    f"File processing failed: {self._file_error_message(result)}"
                )
            if state != "ACTIVE":
                result = await self._wait_for_file_active(file_name)

            file_uri = getattr(result, "uri", None)
            if not isinstance(file_uri, str) or not file_uri:
                raise APIError("Gemini upload did not return a file uri")

            return file_uri
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="gemini",
                phase="upload",
                allow_network_errors=False,
                message="Gemini upload failed",
            ) from e

    @staticmethod
    def _file_state_name(file_obj: Any) -> str:
        """Extract a stable string state from Gemini file objects."""
        state = getattr(file_obj, "state", None)
        if isinstance(state, str) and state:
            return state

        for attr in ("name", "value"):
            value = getattr(state, attr, None)
            if isinstance(value, str) and value:
                return value

        return "STATE_UNSPECIFIED"

    @staticmethod
    def _file_error_message(file_obj: Any) -> str:
        """Extract a human-readable processing error message."""
        error = getattr(file_obj, "error", None)
        if isinstance(error, str) and error:
            return error

        message = getattr(error, "message", None)
        if isinstance(message, str) and message:
            return message

        return "Unknown error"

    async def create_cache(
        self,
        *,
        model: str,
        parts: list[Any],
        system_instruction: str | None = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """Create a cached content entry."""
        client = self._get_client()
        from google.genai import types

        try:
            result = await client.aio.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    contents=self._convert_parts(parts),
                    system_instruction=system_instruction,
                    ttl=f"{ttl_seconds}s",
                ),
            )
            return str(result.name)
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="gemini",
                phase="cache",
                allow_network_errors=False,
                message="Gemini cache creation failed",
            ) from e

    def _parse_response(self, response: Any) -> dict[str, Any]:
        """Parse Gemini response into a standard dict."""
        text = ""
        structured: Any = None
        try:
            if hasattr(response, "text"):
                text = response.text or ""
            # Fallbacks similar to before, but new SDK usually gives .text
            # if candidates exist and have text.
        except Exception:
            text = ""
        try:
            structured = getattr(response, "parsed", None)
            if structured is None and text:
                structured = json.loads(text)
        except Exception:
            structured = None

        usage = {}
        try:
            if hasattr(response, "usage_metadata"):
                um = response.usage_metadata
                # Gemini SDK attrs → provider-agnostic keys
                usage = {
                    "input_tokens": getattr(um, "prompt_token_count", 0),
                    "output_tokens": getattr(um, "candidates_token_count", 0),
                    "total_tokens": getattr(um, "total_token_count", 0),
                }
        except Exception:
            usage = {}

        tool_calls = []
        if hasattr(response, "function_calls") and response.function_calls:
            for fc in response.function_calls:
                tool_calls.append(
                    {
                        "id": getattr(fc, "id", None),
                        "name": getattr(fc, "name", None),
                        "arguments": getattr(fc, "args", {}),
                    }
                )

        payload: dict[str, Any] = {"text": text, "usage": usage}
        if structured is not None:
            payload["structured"] = structured
        if tool_calls:
            payload["tool_calls"] = tool_calls
        return payload
