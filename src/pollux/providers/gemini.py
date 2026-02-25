"""Gemini provider implementation."""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any
import uuid

from pollux.errors import APIError
from pollux.providers._errors import wrap_provider_error
from pollux.providers.base import ProviderCapabilities
from pollux.providers.models import Message, ProviderRequest, ProviderResponse, ToolCall

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
            reasoning=True,
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
        request: ProviderRequest,
    ) -> ProviderResponse:
        """Generate content from the Gemini model."""
        client = self._get_client()
        from google.genai import types

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

        config_kwargs: dict[str, Any] = {}
        if reasoning_effort is not None:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                include_thoughts=True,
                thinking_level=reasoning_effort,  # type: ignore[arg-type]
            )

        if system_instruction is not None:
            config_kwargs["system_instruction"] = system_instruction
        if cache_name is not None:
            config_kwargs["cached_content"] = cache_name
        if response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_json_schema"] = response_schema
        if temperature is not None:
            config_kwargs["temperature"] = temperature
        if top_p is not None:
            config_kwargs["top_p"] = top_p

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
                config_kwargs["tools"] = tool_objs

            if isinstance(tool_choice, str):
                mode = tool_choice.upper()
                if mode in ("AUTO", "ANY", "NONE"):
                    config_kwargs["tool_config"] = {
                        "function_calling_config": {"mode": mode}
                    }
                elif mode == "REQUIRED":
                    config_kwargs["tool_config"] = {
                        "function_calling_config": {"mode": "ANY"}
                    }
            elif isinstance(tool_choice, dict) and "name" in tool_choice:
                # Force specific function
                config_kwargs["tool_config"] = {
                    "function_calling_config": {
                        "mode": "ANY",
                        "allowed_function_names": [tool_choice["name"]],
                    }
                }

        input_contents = []
        call_id_to_name: dict[str, str] = {}

        if history:

            def append_history(items: list[Message]) -> None:
                for item in items:
                    if item.role == "tool":
                        call_id = item.tool_call_id
                        name = "unknown_tool"
                        if isinstance(call_id, str) and call_id in call_id_to_name:
                            name = call_id_to_name[call_id]

                        parsed_content: dict[str, Any] = {}
                        if item.content:
                            try:
                                parsed_content = json.loads(item.content)
                                if not isinstance(parsed_content, dict):
                                    parsed_content = {"result": item.content}
                            except Exception:
                                parsed_content = {"result": item.content}

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
                    elif item.role == "assistant":
                        ast_parts: list[Any] = []
                        if item.content:
                            ast_parts.append(types.Part.from_text(text=item.content))
                        if item.tool_calls:
                            for tc in item.tool_calls:
                                call_id_to_name[tc.id] = tc.name
                                try:
                                    args_dict = json.loads(tc.arguments)
                                except Exception:
                                    args_dict = {}
                                ast_parts.append(
                                    types.Part.from_function_call(
                                        name=tc.name, args=args_dict
                                    )
                                )
                        if ast_parts:
                            input_contents.append(
                                types.Content(role="model", parts=ast_parts)
                            )
                    elif item.role == "user":
                        user_parts: list[Any] = []
                        if item.content:
                            user_parts.append(types.Part.from_text(text=item.content))
                        if user_parts:
                            input_contents.append(
                                types.Content(role="user", parts=user_parts)
                            )

            append_history(history)

        if not input_contents:
            # No history — use the original flat-parts path unchanged.
            contents: Any = self._convert_parts(parts)
        else:
            # Gemini enforces strict turn order: after a function response the
            # model must speak next.  Appending a separate user Content would
            # produce FunctionResponse → User → Model, which is rejected.
            # Instead, merge the prompt parts into the existing function-
            # response Content block (same "user" role) so the model still
            # sees the instruction without a turn-order violation.
            last_is_tool_response = bool(history and history[-1].role == "tool")
            user_parts: list[Any] = []
            for cp in self._convert_parts(parts):
                if isinstance(cp, str):
                    user_parts.append(types.Part.from_text(text=cp))
                else:
                    user_parts.append(cp)
            if user_parts:
                last_parts = (
                    input_contents[-1].parts
                    if last_is_tool_response and input_contents
                    else None
                )
                if last_parts is not None:
                    # Fold into the trailing function-response Content.
                    last_parts.extend(user_parts)
                else:
                    input_contents.append(types.Content(role="user", parts=user_parts))
            contents = input_contents

        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )

            if not response:
                raise APIError("Gemini returned an empty response.")

            return self._parse_response(response)
        except asyncio.CancelledError:
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

    def _parse_response(self, response: Any) -> ProviderResponse:
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
                thoughts_toks = getattr(um, "thoughts_token_count", None)
                if thoughts_toks is not None:
                    usage["reasoning_tokens"] = thoughts_toks
        except Exception:
            usage = {}

        tool_calls: list[ToolCall] = []
        if hasattr(response, "function_calls") and response.function_calls:
            for fc in response.function_calls:
                call_id = fc.id or f"call_{uuid.uuid4().hex[:8]}"

                # Gemini args are typed as Optional[dict[str, Any]].
                # We default to an empty dictionary to ensure valid JSON output.
                args_str = json.dumps(fc.args or {})

                tool_calls.append(
                    ToolCall(
                        id=str(call_id),
                        name=str(fc.name),
                        arguments=args_str,
                    )
                )

        reasoning_parts = []
        try:
            if hasattr(response, "candidates") and response.candidates:
                content = response.candidates[0].content
                if hasattr(content, "parts"):
                    for part in content.parts:
                        if getattr(part, "thought", False) and getattr(
                            part, "text", None
                        ):
                            reasoning_parts.append(part.text)
        except Exception:
            reasoning_parts.clear()

        return ProviderResponse(
            text=text,
            usage=usage,
            reasoning="\n\n".join(reasoning_parts).strip() if reasoning_parts else None,
            structured=structured,
            tool_calls=tool_calls if tool_calls else None,
            response_id=None,
        )
