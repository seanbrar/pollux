"""Gemini provider implementation."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
import json
import logging
from pathlib import Path
import tempfile
import time
from typing import Any
import uuid

from pollux.errors import APIError, ConfigurationError
from pollux.providers._errors import wrap_provider_error
from pollux.providers.base import (
    DeferredItemStatus,
    ProviderCapabilities,
    ProviderDeferredHandle,
    ProviderDeferredItem,
    ProviderDeferredSnapshot,
)
from pollux.providers.models import (
    Message,
    ProviderFileAsset,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
)

logger = logging.getLogger(__name__)

_GEMINI_BATCH_INLINE_LIMIT_BYTES = 20_000_000


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
    def capabilities(self) -> ProviderCapabilities:
        """Return supported feature flags."""
        return ProviderCapabilities(
            persistent_cache=True,
            uploads=True,
            structured_outputs=True,
            reasoning=True,
            deferred_delivery=True,
            conversation=True,
        )

    def _convert_parts(self, parts: list[Any]) -> list[Any]:
        """Convert internal part representation to google-genai SDK types."""
        from google.genai import types

        converted: list[Any] = []
        for p in parts:
            if isinstance(p, str):
                converted.append(p)
            elif isinstance(p, ProviderFileAsset):
                if p.provider != "gemini":
                    raise APIError(f"Gemini cannot use {p.provider} file assets.")
                converted.append(
                    types.Part(
                        file_data=types.FileData(
                            file_uri=p.file_id, mime_type=p.mime_type
                        )
                    )
                )
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

    def _normalize_tools(self, tools: list[dict[str, Any]]) -> list[Any]:
        """Convert tool dicts to Gemini FunctionDeclaration-wrapped Tools."""
        from google.genai import types

        tool_objs: list[Any] = []
        for t in tools:
            if not isinstance(t, dict):
                raise ConfigurationError(
                    f"Tool must be a dictionary, got {type(t).__name__}",
                    hint="Ensure all items in the tools list are dictionaries.",
                )
            if "name" in t:
                raw_params = t.get("parameters")
                params = (
                    _strip_additional_properties(raw_params)
                    if isinstance(raw_params, dict)
                    else raw_params
                )
                tool_objs.append(
                    types.Tool(
                        function_declarations=[
                            types.FunctionDeclaration(
                                name=t["name"],
                                description=t.get("description", ""),
                                parameters=params,  # type: ignore[arg-type]
                            )
                        ]
                    )
                )
        return tool_objs

    def _map_tool_choice(
        self, tool_choice: str | dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Map tool_choice to Gemini tool_config dict."""
        if isinstance(tool_choice, str):
            mode = tool_choice.upper()
            if mode in ("AUTO", "ANY", "NONE"):
                return {"function_calling_config": {"mode": mode}}
            if mode == "REQUIRED":
                return {"function_calling_config": {"mode": "ANY"}}
        elif isinstance(tool_choice, dict) and "name" in tool_choice:
            return {
                "function_calling_config": {
                    "mode": "ANY",
                    "allowed_function_names": [tool_choice["name"]],
                }
            }
        return None

    def _build_config_kwargs(self, request: ProviderRequest) -> dict[str, Any]:
        """Assemble Gemini GenerateContentConfig keyword arguments."""
        from google.genai import types

        config_kwargs: dict[str, Any] = {}

        if request.reasoning_effort is not None:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                include_thoughts=True,
                thinking_level=request.reasoning_effort,  # type: ignore[arg-type]
            )

        if request.system_instruction is not None:
            config_kwargs["system_instruction"] = request.system_instruction
        if request.cache_name is not None:
            config_kwargs["cached_content"] = request.cache_name
        if request.response_schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_json_schema"] = request.response_schema
        if request.temperature is not None:
            config_kwargs["temperature"] = request.temperature
        if request.top_p is not None:
            config_kwargs["top_p"] = request.top_p

        if request.tools is not None:
            tool_objs = self._normalize_tools(request.tools)
            if tool_objs:
                config_kwargs["tools"] = tool_objs

            tool_config = self._map_tool_choice(request.tool_choice)
            if tool_config is not None:
                config_kwargs["tool_config"] = tool_config

        return config_kwargs

    def _build_contents(
        self,
        parts: list[Any],
        history: list[Message] | None,
    ) -> Any:
        """Build Gemini contents from history + current parts."""
        from google.genai import types

        input_contents: list[Any] = []
        call_id_to_name: dict[str, str] = {}

        if history:
            for item in history:
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

        if not input_contents:
            return self._convert_parts(parts)

        # Gemini enforces strict turn order: after a function response the
        # model must speak next.  Appending a separate user Content would
        # produce FunctionResponse → User → Model, which is rejected.
        # Instead, merge the prompt parts into the existing function-
        # response Content block (same "user" role) so the model still
        # sees the instruction without a turn-order violation.
        last_is_tool_response = bool(history and history[-1].role == "tool")
        user_parts_list: list[Any] = []
        for cp in self._convert_parts(parts):
            if isinstance(cp, str):
                user_parts_list.append(types.Part.from_text(text=cp))
            else:
                user_parts_list.append(cp)
        if user_parts_list:
            last_parts = (
                input_contents[-1].parts
                if last_is_tool_response and input_contents
                else None
            )
            if last_parts is not None:
                last_parts.extend(user_parts_list)
            else:
                input_contents.append(types.Content(role="user", parts=user_parts_list))
        return input_contents

    async def submit_deferred(
        self,
        requests: list[ProviderRequest],
        *,
        request_ids: list[str],
    ) -> ProviderDeferredHandle:
        """Submit deferred work through the Gemini Batch API."""
        client = self._get_client()
        from google.genai import types

        temp_batch_path: Path | None = None
        try:
            upload_cache: dict[tuple[str, str], ProviderFileAsset] = {}
            inlined_requests: list[Any] | None = []
            payload_bytes = 0
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".jsonl",
                prefix="pollux-gemini-batch-",
                delete=False,
            ) as temp_batch:
                temp_batch_path = Path(temp_batch.name)
                for request_id, request in zip(request_ids, requests, strict=True):
                    resolved_request = await self._resolve_deferred_request(
                        request,
                        upload_cache=upload_cache,
                    )
                    inlined_request = types.InlinedRequest(
                        contents=self._build_contents(
                            resolved_request.parts,
                            resolved_request.history,
                        ),
                        config=types.GenerateContentConfig(
                            **self._build_config_kwargs(resolved_request)
                        ),
                        metadata={"pollux_request_id": request_id},
                    )
                    if inlined_requests is not None:
                        inlined_requests.append(inlined_request)

                    batch_line = self._serialize_deferred_request(inlined_request)
                    encoded_line = (
                        json.dumps(batch_line, separators=(",", ":")) + "\n"
                    ).encode("utf-8")
                    temp_batch.write(encoded_line)
                    payload_bytes += len(encoded_line)
                    if payload_bytes > _GEMINI_BATCH_INLINE_LIMIT_BYTES:
                        inlined_requests = None

            owned_file_ids = _owned_deferred_file_ids(upload_cache)
            if inlined_requests is not None:
                batch = await client.aio.batches.create(
                    model=requests[0].model,
                    src=inlined_requests,
                )
            else:
                batch_input_file = await self._upload_deferred_batch_input_file(
                    temp_batch_path
                )
                owned_file_ids.append(batch_input_file)
                batch = await client.aio.batches.create(
                    model=requests[0].model,
                    src=types.BatchJobSource(file_name=batch_input_file),
                )
            return ProviderDeferredHandle(
                job_id=str(batch.name),
                submitted_at=_timestamp_or_none(batch.create_time),
                provider_state={
                    "request_ids": list(request_ids),
                    "owned_file_ids": sorted(set(owned_file_ids)),
                    "has_response_schema": _requests_have_response_schema(requests),
                },
            )
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="gemini",
                phase="batch_submit",
                allow_network_errors=False,
                message="Gemini batch submit failed",
            ) from e
        finally:
            if temp_batch_path is not None:
                with contextlib.suppress(OSError):
                    temp_batch_path.unlink()

    async def inspect_deferred(
        self, handle: ProviderDeferredHandle
    ) -> ProviderDeferredSnapshot:
        """Inspect a Gemini batch and normalize status/counts."""
        client = self._get_client()
        status: str | None = None

        try:
            batch = await client.aio.batches.get(name=handle.job_id)
            request_ids = _provider_handle_request_ids(handle)
            total = len(request_ids) if request_ids is not None else 0
            succeeded, failed, pending = _batch_counts(batch, total=total)
            status = _normalize_batch_status(
                _job_state_name(batch.state),
                succeeded=succeeded,
                failed=failed,
            )
            return ProviderDeferredSnapshot(
                status=status,
                provider_status=_job_state_name(batch.state),
                request_count=total or succeeded + failed + pending,
                succeeded=succeeded,
                failed=failed,
                pending=pending,
                submitted_at=_timestamp_or_none(batch.create_time),
                completed_at=_timestamp_or_none(batch.end_time),
                expires_at=None,
            )
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="gemini",
                phase="batch_inspect",
                allow_network_errors=True,
                message="Gemini batch inspect failed",
            ) from e
        finally:
            if status in {"completed", "partial", "failed", "cancelled", "expired"}:
                await self._cleanup_deferred_owned_files(handle)

    async def collect_deferred(
        self, handle: ProviderDeferredHandle
    ) -> list[ProviderDeferredItem]:
        """Collect Gemini batch results into deferred items."""
        client = self._get_client()

        try:
            batch = await client.aio.batches.get(name=handle.job_id)
            request_ids = _provider_handle_request_ids(handle) or []
            items: list[ProviderDeferredItem] = []
            inlined_responses = _batch_inlined_responses(batch)
            if inlined_responses is not None:
                items.extend(
                    self._parse_inlined_batch_responses(
                        inlined_responses,
                        request_ids=request_ids,
                    )
                )
            else:
                output_file_name = _batch_output_file_name(batch)
                if output_file_name is None:
                    output_file_name = ""
                if output_file_name:
                    content = await client.aio.files.download(file=output_file_name)
                    items.extend(
                        self._parse_batch_output_file(
                            content,
                            request_ids=request_ids,
                        )
                    )

            synthesized = self._synthesize_terminal_batch_items(
                batch,
                handle=handle,
                existing_request_ids={item.request_id for item in items},
            )
            if synthesized is not None:
                items.extend(synthesized)

            await self._cleanup_deferred_owned_files(handle)
            return items
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="gemini",
                phase="batch_collect",
                allow_network_errors=True,
                message="Gemini batch collect failed",
            ) from e

    async def cancel_deferred(self, handle: ProviderDeferredHandle) -> None:
        """Cancel a Gemini batch."""
        client = self._get_client()

        try:
            await client.aio.batches.cancel(name=handle.job_id)
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="gemini",
                phase="batch_cancel",
                allow_network_errors=True,
                message="Gemini batch cancel failed",
            ) from e

    async def generate(
        self,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """Generate content from the Gemini model."""
        client = self._get_client()
        from google.genai import types

        config_kwargs = self._build_config_kwargs(request)
        contents = self._build_contents(request.parts, request.history)

        try:
            response = await client.aio.models.generate_content(
                model=request.model,
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

    async def _resolve_deferred_request(
        self,
        request: ProviderRequest,
        *,
        upload_cache: dict[tuple[str, str], ProviderFileAsset],
    ) -> ProviderRequest:
        """Resolve local file parts into provider assets for deferred submission."""
        resolved_parts: list[Any] = []
        for part in request.parts:
            if (
                isinstance(part, dict)
                and isinstance(part.get("file_path"), str)
                and isinstance(part.get("mime_type"), str)
            ):
                file_path = part["file_path"]
                mime_type = part["mime_type"]
                cache_key = (file_path, mime_type)
                asset = upload_cache.get(cache_key)
                if asset is None:
                    from pathlib import Path

                    asset = await self.upload_file(Path(file_path), mime_type)
                    upload_cache[cache_key] = asset
                resolved_parts.append(asset)
            else:
                resolved_parts.append(part)

        return ProviderRequest(
            model=request.model,
            parts=resolved_parts,
            system_instruction=request.system_instruction,
            cache_name=request.cache_name,
            response_schema=request.response_schema,
            temperature=request.temperature,
            top_p=request.top_p,
            tools=request.tools,
            tool_choice=request.tool_choice,
            reasoning_effort=request.reasoning_effort,
            history=request.history,
            previous_response_id=request.previous_response_id,
            provider_state=request.provider_state,
            max_tokens=request.max_tokens,
            implicit_caching=request.implicit_caching,
        )

    async def _upload_deferred_batch_input_file(self, path: Path) -> str:
        """Upload a JSONL batch input file and return its file resource name."""
        client = self._get_client()

        try:
            with path.open("rb") as upload:
                result = await client.aio.files.upload(
                    file=upload,
                    config={"mime_type": "application/jsonl"},
                )

            file_name = getattr(result, "name", None)
            if not isinstance(file_name, str) or not file_name:
                raise APIError("Gemini batch input upload did not return a file name")

            state = self._file_state_name(result)
            if state == "FAILED":
                raise APIError(
                    "Batch input file processing failed: "
                    f"{self._file_error_message(result)}"
                )
            if state != "ACTIVE":
                result = await self._wait_for_file_active(file_name)

            active_file_name = getattr(result, "name", None)
            if not isinstance(active_file_name, str) or not active_file_name:
                raise APIError(
                    "Gemini batch input upload did not return an active file name"
                )
            return active_file_name
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="gemini",
                phase="batch_upload",
                allow_network_errors=False,
                message="Gemini batch input upload failed",
            ) from e

    async def upload_file(self, path: Path, mime_type: str) -> ProviderFileAsset:
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

            return ProviderFileAsset(
                file_id=file_uri,
                provider="gemini",
                mime_type=mime_type,
                file_name=file_name,
            )
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
        tools: list[dict[str, Any]] | list[Any] | None = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """Create a cached content entry."""
        client = self._get_client()
        from google.genai import types

        config_kwargs: dict[str, Any] = {
            "contents": self._convert_parts(parts),
            "system_instruction": system_instruction,
            "ttl": f"{ttl_seconds}s",
        }

        try:
            if tools is not None:
                tool_objs = self._normalize_tools(tools)
                if tool_objs:
                    config_kwargs["tools"] = tool_objs

            result = await client.aio.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(**config_kwargs),
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

    async def delete_file(self, file_id: str) -> None:
        """Delete a previously uploaded file from Gemini storage."""
        client = self._get_client()
        await client.aio.files.delete(name=file_id)

    async def _cleanup_deferred_owned_files(
        self, handle: ProviderDeferredHandle
    ) -> None:
        """Best-effort cleanup for provider-owned deferred input files."""
        for file_id in _provider_handle_owned_file_ids(handle):
            try:
                await self.delete_file(file_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("Gemini deferred cleanup failed for file_id=%s", file_id)

    def _parse_inlined_batch_responses(
        self,
        responses: list[Any],
        *,
        request_ids: list[str],
    ) -> list[ProviderDeferredItem]:
        """Parse Gemini inlined batch responses into deferred items."""
        items: list[ProviderDeferredItem] = []
        for index, entry in enumerate(responses):
            request_id = _inlined_response_request_id(entry)
            if request_id is None and index < len(request_ids):
                request_id = request_ids[index]
            if request_id is None:
                request_id = f"pollux-{index:06d}"

            error = _field(entry, "error")
            raw_response = _field(entry, "response")
            if raw_response is None:
                items.append(
                    ProviderDeferredItem(
                        request_id=request_id,
                        status="failed",
                        error=_job_error_message(error),
                        provider_status=_job_error_code(error),
                    )
                )
                continue

            parsed = self._parse_response(raw_response)
            items.append(
                ProviderDeferredItem(
                    request_id=request_id,
                    status="succeeded",
                    response=_provider_response_to_dict(parsed),
                    provider_status="succeeded",
                    finish_reason=parsed.finish_reason,
                )
            )
        return items

    def _parse_batch_output_file(
        self,
        content: bytes,
        *,
        request_ids: list[str],
    ) -> list[ProviderDeferredItem]:
        """Parse a Gemini JSONL output file into deferred items."""
        items: list[ProviderDeferredItem] = []
        for index, line in enumerate(content.decode("utf-8").splitlines()):
            if not line.strip():
                continue
            payload = json.loads(line)
            request_id = _batch_file_request_id(
                payload,
                index=index,
                request_ids=request_ids,
            )
            response = _field(payload, "response")
            error = _field(payload, "error")
            if response is None and error is None and isinstance(payload, dict):
                response = payload

            if not isinstance(response, dict):
                items.append(
                    ProviderDeferredItem(
                        request_id=request_id,
                        status="failed",
                        error=_job_error_message(error),
                        provider_status=_job_error_code(error),
                    )
                )
                continue

            parsed = self._parse_response(response)
            items.append(
                ProviderDeferredItem(
                    request_id=request_id,
                    status="succeeded",
                    response=_provider_response_to_dict(parsed),
                    provider_status="succeeded",
                    finish_reason=parsed.finish_reason,
                )
            )
        return items

    @staticmethod
    def _serialize_deferred_request(request: Any) -> dict[str, Any]:
        """Serialize one Gemini deferred request into the JSONL file shape."""
        normalized_request = request.model_copy(
            update={
                "contents": GeminiProvider._normalize_batch_request_contents(
                    request.contents
                )
            }
        )
        payload = normalized_request.model_dump(exclude_none=True, by_alias=True)
        request_payload: dict[str, Any] = {}

        model = payload.pop("model", None)
        if model is not None:
            request_payload["model"] = model

        contents = payload.pop("contents", None)
        if contents is not None:
            request_payload["contents"] = contents

        config = payload.pop("config", None)
        if config is not None:
            request_payload["generationConfig"] = config

        line: dict[str, Any] = {"request": request_payload}
        metadata = payload.pop("metadata", None)
        if metadata is not None:
            line["metadata"] = metadata
        return line

    @staticmethod
    def _normalize_batch_request_contents(contents: Any) -> Any:
        """Normalize inline-friendly contents into explicit Content objects."""
        from google.genai import types

        if contents is None:
            return None
        if _is_content_list(contents):
            return contents
        if isinstance(contents, list):
            return [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=item)
                        if isinstance(item, str)
                        else item
                        for item in contents
                    ],
                )
            ]
        return [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=contents)
                    if isinstance(contents, str)
                    else contents
                ],
            )
        ]

    def _synthesize_terminal_batch_items(
        self,
        batch: Any,
        *,
        handle: ProviderDeferredHandle,
        existing_request_ids: set[str],
    ) -> list[ProviderDeferredItem] | None:
        """Expand missing terminal batch rows into per-request diagnostics."""
        item_status = _batch_level_item_status(_job_state_name(batch.state))
        if item_status is None:
            return None

        request_ids = _provider_handle_request_ids(handle)
        if request_ids is None:
            return None
        missing_request_ids = [
            request_id
            for request_id in request_ids
            if request_id not in existing_request_ids
        ]
        if not missing_request_ids:
            return None

        error_message = _job_error_message(getattr(batch, "error", None))
        provider_status = _job_error_code(getattr(batch, "error", None))
        if provider_status is None:
            provider_status = _job_state_name(batch.state)

        return [
            ProviderDeferredItem(
                request_id=request_id,
                status=item_status,
                error=error_message,
                provider_status=provider_status,
            )
            for request_id in missing_request_ids
        ]

    def _parse_response(self, response: Any) -> ProviderResponse:
        """Parse Gemini response into a standard dict."""
        text = _extract_response_text(response)
        structured: Any = None
        try:
            structured = _field(response, "parsed")
            if structured is None and text:
                structured = json.loads(text)
        except Exception:
            structured = None

        usage = {}
        try:
            usage_metadata = _field(response, "usage_metadata")
            if usage_metadata is not None:
                # Gemini SDK attrs → provider-agnostic keys
                usage = {
                    "input_tokens": int(
                        _field(usage_metadata, "prompt_token_count", 0) or 0
                    ),
                    "output_tokens": int(
                        _field(usage_metadata, "candidates_token_count", 0) or 0
                    ),
                    "total_tokens": int(
                        _field(usage_metadata, "total_token_count", 0) or 0
                    ),
                }
                thoughts_toks = _field(usage_metadata, "thoughts_token_count")
                if thoughts_toks is not None:
                    usage["reasoning_tokens"] = int(thoughts_toks)
        except Exception:
            usage = {}

        tool_calls: list[ToolCall] = []
        function_calls = _field(response, "function_calls", []) or []
        if isinstance(function_calls, list):
            for function_call in function_calls:
                call_id = _field(function_call, "id") or f"call_{uuid.uuid4().hex[:8]}"

                # Gemini args are typed as Optional[dict[str, Any]].
                # We default to an empty dictionary to ensure valid JSON output.
                args_str = json.dumps(_field(function_call, "args") or {})

                tool_calls.append(
                    ToolCall(
                        id=str(call_id),
                        name=str(_field(function_call, "name", "")),
                        arguments=args_str,
                    )
                )

        finish_reason: str | None = None
        reasoning_parts: list[str] = []
        try:
            candidates = _field(response, "candidates", []) or []
            if isinstance(candidates, list) and candidates:
                candidate = candidates[0]
                finish_reason = _normalize_finish_reason(
                    _field(candidate, "finish_reason")
                )
                content = _field(candidate, "content")
                parts = _field(content, "parts", []) if content is not None else []
                if isinstance(parts, list):
                    for part in parts:
                        part_text = _field(part, "text")
                        if _field(part, "thought", default=False) and isinstance(
                            part_text, str
                        ):
                            reasoning_parts.append(part_text)
        except Exception:
            reasoning_parts.clear()

        return ProviderResponse(
            text=text,
            usage=usage,
            reasoning="\n\n".join(reasoning_parts).strip() if reasoning_parts else None,
            structured=structured,
            tool_calls=tool_calls if tool_calls else None,
            response_id=None,
            finish_reason=finish_reason,
        )


def _field(obj: Any, key: str, default: Any = None) -> Any:
    """Read a field from either an SDK object or a raw JSON dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_response_text(response: Any) -> str:
    """Extract text from Gemini responses and raw batch JSON."""
    text = _field(response, "text")
    if isinstance(text, str) and text:
        return text

    parts: list[str] = []
    candidates = _field(response, "candidates", []) or []
    if not isinstance(candidates, list):
        return ""
    for candidate in candidates:
        content = _field(candidate, "content")
        candidate_parts = _field(content, "parts", []) if content is not None else []
        if not isinstance(candidate_parts, list):
            continue
        for part in candidate_parts:
            part_text = _field(part, "text")
            if (
                isinstance(part_text, str)
                and part_text
                and not _field(part, "thought", default=False)
            ):
                parts.append(part_text)
    return "".join(parts)


def _is_content_list(value: Any) -> bool:
    """Return True when the payload is already a Gemini content sequence."""
    if not isinstance(value, list) or not value:
        return False
    return all(_is_content_like(item) for item in value)


def _is_content_like(value: Any) -> bool:
    """Best-effort detection for Gemini Content-like objects."""
    if isinstance(value, dict):
        return "parts" in value and "role" in value
    return hasattr(value, "parts") and hasattr(value, "role")


def _timestamp_or_none(value: Any) -> float | None:
    """Convert datetimes or unix timestamps to floats when present."""
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _provider_handle_request_ids(handle: ProviderDeferredHandle) -> list[str] | None:
    """Return the submitted Pollux request ids stored in the provider handle."""
    provider_state = handle.provider_state
    if not isinstance(provider_state, dict):
        return None
    raw_ids = provider_state.get("request_ids")
    if not isinstance(raw_ids, list):
        return None

    request_ids: list[str] = []
    for value in raw_ids:
        if not isinstance(value, str) or not value:
            return None
        request_ids.append(value)
    return request_ids


def _provider_handle_owned_file_ids(handle: ProviderDeferredHandle) -> list[str]:
    """Return provider-owned file ids stored on the deferred handle."""
    provider_state = handle.provider_state
    if not isinstance(provider_state, dict):
        return []
    raw_ids = provider_state.get("owned_file_ids")
    if not isinstance(raw_ids, list):
        return []
    return [value for value in raw_ids if isinstance(value, str) and value]


def _owned_deferred_file_ids(
    upload_cache: dict[tuple[str, str], ProviderFileAsset],
) -> list[str]:
    """Return provider-owned remote file ids created during deferred submission."""
    file_ids = {
        asset.file_name or asset.file_id
        for asset in upload_cache.values()
        if asset.file_id
    }
    return sorted(file_ids)


def _requests_have_response_schema(requests: list[ProviderRequest]) -> bool:
    """Persist whether structured outputs were enabled at submission time."""
    return any(request.response_schema is not None for request in requests)


def _job_state_name(state: Any) -> str:
    """Return a stable Gemini job state string."""
    value = getattr(state, "name", None) or getattr(state, "value", None) or state
    if isinstance(value, str) and value:
        return value.upper()
    return "JOB_STATE_UNSPECIFIED"


def _batch_inlined_responses(batch: Any) -> list[Any] | None:
    """Return inlined batch responses when present."""
    dest = _field(batch, "dest")
    responses = _field(dest, "inlined_responses") if dest is not None else None
    return responses if isinstance(responses, list) else None


def _batch_output_file_name(batch: Any) -> str | None:
    """Return the batch output file resource name when present."""
    dest = _field(batch, "dest")
    file_name = _field(dest, "file_name") if dest is not None else None
    return file_name if isinstance(file_name, str) and file_name else None


def _batch_counts(batch: Any, *, total: int) -> tuple[int, int, int]:
    """Return normalized succeeded/failed/pending counts for a Gemini batch."""
    responses = _batch_inlined_responses(batch)
    if responses is not None:
        succeeded = sum(
            1 for response in responses if _field(response, "response") is not None
        )
        failed = len(responses) - succeeded
        pending = max(total - len(responses), 0)
        if _job_state_name(_field(batch, "state")) in {
            "JOB_STATE_SUCCEEDED",
            "JOB_STATE_FAILED",
            "JOB_STATE_CANCELLED",
            "JOB_STATE_EXPIRED",
            "JOB_STATE_PARTIALLY_SUCCEEDED",
        }:
            pending = 0
            failed += max(total - len(responses), 0)
        return succeeded, failed, pending

    completion_stats = _field(batch, "completion_stats")
    successful = _field(completion_stats, "successful_count")
    failed = _field(completion_stats, "failed_count")
    incomplete = _field(completion_stats, "incomplete_count")
    if isinstance(successful, int) and isinstance(failed, int):
        pending = max(total - successful - failed, 0)
        if isinstance(incomplete, int) and incomplete >= 0:
            pending = incomplete
        return successful, failed, pending

    raw_state = _job_state_name(_field(batch, "state"))
    if raw_state == "JOB_STATE_SUCCEEDED":
        return total, 0, 0
    if raw_state == "JOB_STATE_PARTIALLY_SUCCEEDED":
        return 0, total, 0
    if raw_state in {"JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}:
        return 0, total, 0
    return 0, 0, total


def _normalize_batch_status(
    raw_state: str,
    *,
    succeeded: int,
    failed: int,
) -> str:
    """Map Gemini batch job states into Pollux deferred statuses."""
    if raw_state in {"JOB_STATE_QUEUED", "JOB_STATE_PENDING"}:
        return "queued"
    if raw_state in {"JOB_STATE_RUNNING", "JOB_STATE_PAUSED", "JOB_STATE_UPDATING"}:
        return "running"
    if raw_state == "JOB_STATE_CANCELLING":
        return "cancelling"
    if raw_state == "JOB_STATE_SUCCEEDED":
        if succeeded > 0 and failed > 0:
            return "partial"
        if succeeded > 0:
            return "completed"
        return "failed"
    if raw_state == "JOB_STATE_PARTIALLY_SUCCEEDED":
        return "partial"
    if raw_state == "JOB_STATE_CANCELLED":
        return "partial" if succeeded > 0 or failed > 0 else "cancelled"
    if raw_state == "JOB_STATE_EXPIRED":
        return "partial" if succeeded > 0 or failed > 0 else "expired"
    if raw_state == "JOB_STATE_FAILED":
        return "failed"
    return "running"


def _inlined_response_request_id(entry: Any) -> str | None:
    """Extract the Pollux request id from Gemini inlined response metadata."""
    metadata = _field(entry, "metadata")
    request_id = _field(metadata, "pollux_request_id") if metadata is not None else None
    return request_id if isinstance(request_id, str) and request_id else None


def _batch_file_request_id(
    entry: Any,
    *,
    index: int,
    request_ids: list[str],
) -> str:
    """Recover the Pollux request id from file-backed batch output rows."""
    request_id = _inlined_response_request_id(entry)
    if request_id is not None:
        return request_id
    if index < len(request_ids):
        return request_ids[index]
    return f"pollux-{index:06d}"


def _job_error_message(error: Any) -> str | None:
    """Return a readable message for Gemini job errors."""
    message = _field(error, "message")
    return message if isinstance(message, str) and message else None


def _job_error_code(error: Any) -> str | None:
    """Return a stable string code for Gemini job errors."""
    code = _field(error, "code")
    if isinstance(code, int):
        return str(code)
    if isinstance(code, str) and code:
        return code
    return None


def _provider_response_to_dict(response: ProviderResponse) -> dict[str, Any]:
    """Convert ProviderResponse into the normalized deferred response shape."""
    payload: dict[str, Any] = {"text": response.text, "usage": response.usage}
    if response.reasoning is not None:
        payload["reasoning"] = response.reasoning
    if response.structured is not None:
        payload["structured"] = response.structured
    if response.tool_calls is not None:
        payload["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in response.tool_calls
        ]
    if response.response_id is not None:
        payload["response_id"] = response.response_id
    if response.finish_reason is not None:
        payload["finish_reason"] = response.finish_reason
    return payload


def _batch_level_item_status(raw_state: str) -> DeferredItemStatus | None:
    """Map terminal Gemini batch states into a synthesized item status."""
    if raw_state == "JOB_STATE_FAILED":
        return "failed"
    if raw_state == "JOB_STATE_CANCELLED":
        return "cancelled"
    if raw_state == "JOB_STATE_EXPIRED":
        return "expired"
    if raw_state == "JOB_STATE_PARTIALLY_SUCCEEDED":
        return "failed"
    return None


def _normalize_finish_reason(raw_reason: Any) -> str | None:
    """Normalize Gemini finish_reason to a lowercase string.

    The google.genai FinishReason is a ``(str, Enum)`` whose ``.value`` is the
    bare member name (e.g. ``"STOP"``).  For plain strings, ``getattr`` falls
    through to the string itself.
    """
    if raw_reason is None:
        return None
    value = str(getattr(raw_reason, "value", raw_reason)).strip()
    return value.lower() if value else None


def _strip_additional_properties(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove ``additionalProperties`` from a JSON schema recursively.

    The Gemini API rejects schemas that contain this field, but OpenAI requires
    it.  Stripping it at the provider boundary lets callers define one schema
    for all providers.
    """
    from copy import deepcopy

    cleaned = deepcopy(schema)

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        updated: dict[str, Any] = {}
        for key, value in node.items():
            if key == "additionalProperties":
                continue
            updated[key] = walk(value)
        return updated

    result = walk(cleaned)
    return result if isinstance(result, dict) else schema
