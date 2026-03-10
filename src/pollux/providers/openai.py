"""OpenAI provider implementation."""

from __future__ import annotations

import asyncio
import base64
import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pollux.errors import APIError
from pollux.providers._errors import wrap_provider_error
from pollux.providers._utils import to_strict_schema
from pollux.providers.base import (
    DeferredItemStatus,
    ProviderCapabilities,
    ProviderDeferredHandle,
    ProviderDeferredItem,
    ProviderDeferredSnapshot,
)
from pollux.providers.models import (
    ProviderFileAsset,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
)


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
    def capabilities(self) -> ProviderCapabilities:
        """Return supported feature flags."""
        return ProviderCapabilities(
            persistent_cache=False,
            uploads=True,
            structured_outputs=True,
            reasoning=True,
            deferred_delivery=True,
            conversation=True,
        )

    @staticmethod
    def _normalize_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert tool dicts to OpenAI function tool format."""
        result: list[dict[str, Any]] = []
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
                result.append(tool_def)
        return result

    @staticmethod
    def _map_tool_choice(
        tool_choice: str | dict[str, Any] | None,
    ) -> str | dict[str, str] | None:
        """Map tool_choice to OpenAI format."""
        if tool_choice is None:
            return None
        if isinstance(tool_choice, str):
            return tool_choice
        if isinstance(tool_choice, dict) and "name" in tool_choice:
            return {"type": "function", "name": tool_choice["name"]}
        return None

    @staticmethod
    def _build_input(
        parts: list[Any],
        history: list[Any] | None,
        previous_response_id: str | None,
    ) -> list[dict[str, Any]]:
        """Build the input messages list from history + current parts."""
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

        return input_messages

    @staticmethod
    def _parse_response(
        response: Any,
        *,
        response_schema: dict[str, Any] | None,
        parse_structured_json: bool = False,
    ) -> ProviderResponse:
        """Parse an OpenAI response into ProviderResponse."""
        text = _extract_output_text(response)
        response_id = _field(response, "id")
        finish_reason = _extract_finish_reason(response)

        structured: Any = None
        if (response_schema is not None or parse_structured_json) and text:
            try:
                structured = json.loads(text)
            except Exception:
                structured = None

        usage_raw = _field(response, "usage")
        usage: dict[str, int] = {}
        if usage_raw is not None:
            input_tokens = _field(usage_raw, "input_tokens")
            output_tokens = _field(usage_raw, "output_tokens")
            total_tokens = _field(usage_raw, "total_tokens")
            if isinstance(input_tokens, int):
                usage["input_tokens"] = input_tokens
            if isinstance(output_tokens, int):
                usage["output_tokens"] = output_tokens
            if isinstance(total_tokens, int):
                usage["total_tokens"] = total_tokens
            out_details = _field(usage_raw, "output_tokens_details")
            if out_details:
                reasoning_toks = _field(out_details, "reasoning_tokens")
                if reasoning_toks is not None:
                    usage["reasoning_tokens"] = int(reasoning_toks)

        tool_calls: list[ToolCall] = []
        reasoning_parts: list[str] = []
        for item in _field(response, "output", []) or []:
            item_type = _field(item, "type")
            if item_type == "function_call":
                tool_calls.append(
                    ToolCall(
                        id=str(_field(item, "call_id", "")),
                        name=str(_field(item, "name", "")),
                        arguments=str(_field(item, "arguments", "{}") or "{}"),
                    )
                )
            elif item_type == "reasoning":
                for summary_item in _field(item, "summary", []) or []:
                    summary_text = _field(summary_item, "text")
                    if isinstance(summary_text, str) and summary_text:
                        reasoning_parts.append(summary_text)

        return ProviderResponse(
            text=text,
            usage=usage,
            reasoning=(
                "\n\n".join(reasoning_parts).strip() if reasoning_parts else None
            ),
            structured=structured,
            tool_calls=tool_calls if tool_calls else None,
            response_id=response_id if isinstance(response_id, str) else None,
            finish_reason=finish_reason,
        )

    async def submit_deferred(
        self,
        requests: list[ProviderRequest],
        *,
        request_ids: list[str],
    ) -> ProviderDeferredHandle:
        """Submit deferred work through the OpenAI Batch API."""
        client = self._get_client()

        try:
            lines: list[str] = []
            upload_cache: dict[tuple[str, str], ProviderFileAsset] = {}
            for request_id, request in zip(request_ids, requests, strict=True):
                body = await self._build_batch_request_body(
                    request,
                    upload_cache=upload_cache,
                )
                lines.append(
                    json.dumps(
                        {
                            "custom_id": request_id,
                            "method": "POST",
                            "url": "/v1/responses",
                            "body": body,
                        },
                        separators=(",", ":"),
                    )
                )

            payload = ("\n".join(lines) + "\n").encode("utf-8")
            upload = io.BytesIO(payload)
            upload.name = "pollux-batch.jsonl"

            batch_file = await client.files.create(
                file=upload,
                purpose="batch",
            )
            batch = await client.batches.create(
                input_file_id=batch_file.id,
                endpoint="/v1/responses",
                completion_window="24h",
                metadata={
                    "pollux_request_count": str(len(requests)),
                    "pollux_has_response_schema": _batch_has_response_schema(requests),
                },
            )
            return ProviderDeferredHandle(
                job_id=batch.id,
                submitted_at=float(batch.created_at),
            )
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="openai",
                phase="batch_submit",
                allow_network_errors=False,
                message="OpenAI batch submit failed",
            ) from e

    async def inspect_deferred(self, job_id: str) -> ProviderDeferredSnapshot:
        """Inspect an OpenAI batch and normalize status/counts."""
        client = self._get_client()

        try:
            batch = await client.batches.retrieve(job_id)
            total = _batch_total_requests(batch)
            completed = _batch_completed_requests(batch)
            failed = _batch_failed_requests(batch)
            pending = max(total - completed - failed, 0)
            status = _normalize_batch_status(
                _field(batch, "status"),
                completed=completed,
                failed=failed,
            )
            return ProviderDeferredSnapshot(
                status=status,
                provider_status=str(_field(batch, "status", "")),
                request_count=total,
                succeeded=completed,
                failed=failed,
                pending=pending,
                submitted_at=_timestamp_or_none(_field(batch, "created_at")),
                completed_at=_batch_terminal_timestamp(batch),
                expires_at=_timestamp_or_none(_field(batch, "expires_at")),
            )
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="openai",
                phase="batch_inspect",
                allow_network_errors=True,
                message="OpenAI batch inspect failed",
            ) from e

    async def collect_deferred(self, job_id: str) -> list[ProviderDeferredItem]:
        """Collect OpenAI batch output and error files into deferred items."""
        client = self._get_client()

        try:
            batch = await client.batches.retrieve(job_id)
            items: list[ProviderDeferredItem] = []
            parse_structured_json = _batch_metadata_flag(
                _field(batch, "metadata"),
                key="pollux_has_response_schema",
            )
            output_file_id = _field(batch, "output_file_id")
            if isinstance(output_file_id, str) and output_file_id:
                content = await client.files.retrieve_content(output_file_id)
                items.extend(
                    self._parse_batch_output_file(
                        content,
                        parse_structured_json=parse_structured_json,
                    )
                )

            error_file_id = _field(batch, "error_file_id")
            if isinstance(error_file_id, str) and error_file_id:
                content = await client.files.retrieve_content(error_file_id)
                items.extend(self._parse_batch_error_file(content))

            return items
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="openai",
                phase="batch_collect",
                allow_network_errors=True,
                message="OpenAI batch collect failed",
            ) from e

    async def cancel_deferred(self, job_id: str) -> None:
        """Cancel an OpenAI batch."""
        client = self._get_client()
        try:
            await client.batches.cancel(job_id)
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="openai",
                phase="batch_cancel",
                allow_network_errors=True,
                message="OpenAI batch cancel failed",
            ) from e

    async def generate(
        self,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """Generate a response using OpenAI's responses endpoint."""
        _ = request.cache_name
        client = self._get_client()
        create_kwargs = self._build_responses_create_kwargs(request)

        response = await client.responses.create(**create_kwargs)
        return self._parse_response(response, response_schema=request.response_schema)

    async def upload_file(self, path: Path, mime_type: str) -> ProviderFileAsset:
        """Upload a local file and return an asset."""
        client = self._get_client()

        try:
            if _is_text_like_mime_type(mime_type):
                # Files API rejects plain text uploads; inline as input_text payload.
                text = path.read_text(encoding="utf-8")
                encoded = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")
                return ProviderFileAsset(
                    file_id=encoded,
                    provider="openai",
                    mime_type=mime_type,
                    is_inline_fallback=True,
                )

            result = await client.files.create(
                file=path,
                purpose="user_data",
                expires_after={"anchor": "created_at", "seconds": 86_400},
            )

            file_id = getattr(result, "id", None)
            if not isinstance(file_id, str):
                raise APIError("OpenAI upload did not return a file id")
            return ProviderFileAsset(
                file_id=file_id, provider="openai", mime_type=mime_type
            )
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
        tools: list[dict[str, Any]] | list[Any] | None = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """Raise because OpenAI context caching is not supported."""
        _ = model, parts, system_instruction, tools, ttl_seconds
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

    def _build_responses_create_kwargs(
        self, request: ProviderRequest
    ) -> dict[str, Any]:
        """Build the raw `/v1/responses` request body."""
        input_messages = self._build_input(
            request.parts, request.history, request.previous_response_id
        )

        create_kwargs: dict[str, Any] = {
            "model": request.model,
            "input": input_messages,
        }
        if request.temperature is not None:
            create_kwargs["temperature"] = request.temperature
        if request.top_p is not None:
            create_kwargs["top_p"] = request.top_p
        if request.max_tokens is not None:
            create_kwargs["max_output_tokens"] = request.max_tokens

        if request.tools is not None:
            create_kwargs["tools"] = self._normalize_tools(request.tools)
            mapped = self._map_tool_choice(request.tool_choice)
            if mapped is not None:
                create_kwargs["tool_choice"] = mapped

        if request.system_instruction:
            create_kwargs["instructions"] = request.system_instruction
        if request.previous_response_id:
            create_kwargs["previous_response_id"] = request.previous_response_id
        if request.reasoning_effort is not None:
            create_kwargs["reasoning"] = {
                "effort": request.reasoning_effort,
                "summary": "auto",
            }
        if request.response_schema is not None:
            strict_schema = to_strict_schema(request.response_schema)
            create_kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "pollux_structured_output",
                    "schema": strict_schema,
                    "strict": True,
                }
            }

        return create_kwargs

    async def _build_batch_request_body(
        self,
        request: ProviderRequest,
        *,
        upload_cache: dict[tuple[str, str], ProviderFileAsset],
    ) -> dict[str, Any]:
        """Build one OpenAI Batch API line body for `/v1/responses`."""
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
                    asset = await self.upload_file(Path(file_path), mime_type)
                    upload_cache[cache_key] = asset
                resolved_parts.append(asset)
            else:
                resolved_parts.append(part)

        resolved_request = ProviderRequest(
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
        return self._build_responses_create_kwargs(resolved_request)

    def _parse_batch_output_file(
        self,
        content: str,
        *,
        parse_structured_json: bool,
    ) -> list[ProviderDeferredItem]:
        """Parse a batch output JSONL file into succeeded/failed items."""
        items: list[ProviderDeferredItem] = []
        for line in content.splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            request_id = str(payload["custom_id"])
            response = payload.get("response")
            error = payload.get("error")

            if not isinstance(response, dict):
                items.append(
                    ProviderDeferredItem(
                        request_id=request_id,
                        status="failed",
                        error=_error_message(error),
                    )
                )
                continue

            status_code = response.get("status_code")
            body = response.get("body")
            if status_code != 200 or not isinstance(body, dict):
                items.append(
                    ProviderDeferredItem(
                        request_id=request_id,
                        status="failed",
                        error=_error_message(error) or _error_message(body),
                    )
                )
                continue

            parsed = self._parse_response(
                body,
                response_schema=None,
                parse_structured_json=parse_structured_json,
            )
            items.append(
                ProviderDeferredItem(
                    request_id=request_id,
                    status="succeeded",
                    response=_provider_response_to_dict(parsed),
                    provider_status="completed",
                    finish_reason=parsed.finish_reason,
                )
            )
        return items

    def _parse_batch_error_file(self, content: str) -> list[ProviderDeferredItem]:
        """Parse a batch error JSONL file into failed/cancelled/expired items."""
        items: list[ProviderDeferredItem] = []
        for line in content.splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            request_id = str(payload["custom_id"])
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            status = _deferred_status_from_error_code(code)
            items.append(
                ProviderDeferredItem(
                    request_id=request_id,
                    status=status,
                    error=_error_message(error),
                    provider_status=str(code) if isinstance(code, str) else None,
                )
            )
        return items


def _extract_finish_reason(response: Any) -> str | None:
    """Extract OpenAI finish reason, preferring incomplete_details.reason.

    The Responses API exposes ``response.status`` (a string like "completed" or
    "incomplete") and, when incomplete, an ``IncompleteDetails`` model with a
    ``.reason`` field ("max_output_tokens" or "content_filter").  We surface
    the specific reason when available so callers get the actionable root cause.
    """
    status = _field(response, "status")
    if not isinstance(status, str):
        return None

    normalized_status = status.lower()
    if normalized_status == "incomplete":
        details = _field(response, "incomplete_details")
        reason = _field(details, "reason") if details is not None else None
        if isinstance(reason, str) and reason:
            return reason.lower()

    return normalized_status


def _field(obj: Any, key: str, default: Any = None) -> Any:
    """Read a field from either an SDK object or a raw JSON dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_output_text(response: Any) -> str:
    """Extract text from SDK responses and raw batch response bodies."""
    text = _field(response, "output_text")
    if isinstance(text, str) and text:
        return text

    parts: list[str] = []
    for item in _field(response, "output", []) or []:
        if _field(item, "type") != "message":
            continue
        for content in _field(item, "content", []) or []:
            if _field(content, "type") == "output_text":
                value = _field(content, "text")
                if isinstance(value, str):
                    parts.append(value)
    return "".join(parts)


def _timestamp_or_none(value: Any) -> float | None:
    """Convert Unix timestamps to floats when present."""
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _batch_total_requests(batch: Any) -> int:
    """Return the total request count, falling back to batch metadata."""
    counts = _field(batch, "request_counts")
    total = _field(counts, "total") if counts is not None else None
    if isinstance(total, int) and total > 0:
        return total
    metadata = _field(batch, "metadata")
    meta_total = (
        _field(metadata, "pollux_request_count") if metadata is not None else None
    )
    if isinstance(meta_total, str) and meta_total.isdigit():
        return int(meta_total)
    return 0


def _batch_completed_requests(batch: Any) -> int:
    counts = _field(batch, "request_counts")
    value = _field(counts, "completed") if counts is not None else None
    return value if isinstance(value, int) else 0


def _batch_failed_requests(batch: Any) -> int:
    counts = _field(batch, "request_counts")
    value = _field(counts, "failed") if counts is not None else None
    return value if isinstance(value, int) else 0


def _batch_has_response_schema(requests: list[ProviderRequest]) -> str:
    """Persist whether this batch was submitted with structured outputs enabled."""
    return (
        "1" if any(request.response_schema is not None for request in requests) else "0"
    )


def _batch_metadata_flag(metadata: Any, *, key: str) -> bool:
    """Return True when a Pollux-owned batch metadata flag is enabled."""
    value = _field(metadata, key) if metadata is not None else None
    return value == "1"


def _normalize_batch_status(status: Any, *, completed: int, failed: int) -> str:
    """Map OpenAI batch status to Pollux deferred status."""
    raw = str(status).lower() if isinstance(status, str) else ""
    if raw == "validating":
        return "queued"
    if raw in {"in_progress", "finalizing"}:
        return "running"
    if raw == "cancelling":
        return "cancelling"
    if raw == "completed":
        if completed > 0 and failed > 0:
            return "partial"
        if completed > 0:
            return "completed"
        return "failed"
    if raw == "cancelled":
        return "partial" if completed > 0 else "cancelled"
    if raw == "expired":
        return "partial" if completed > 0 else "expired"
    if raw == "failed":
        return "failed"
    return "running"


def _batch_terminal_timestamp(batch: Any) -> float | None:
    """Return the most relevant terminal timestamp for a batch."""
    for key in ("completed_at", "cancelled_at", "expired_at", "failed_at"):
        value = _timestamp_or_none(_field(batch, key))
        if value is not None:
            return value
    return None


def _provider_response_to_dict(response: ProviderResponse) -> dict[str, Any]:
    """Convert ProviderResponse into the normalized response dict shape."""
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


def _error_message(error: Any) -> str | None:
    """Best-effort message extraction from OpenAI batch error payloads."""
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
        code = error.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def _deferred_status_from_error_code(code: Any) -> DeferredItemStatus:
    """Map OpenAI batch error codes to normalized deferred item status."""
    if not isinstance(code, str):
        return "failed"
    if code == "batch_expired":
        return "expired"
    if code in {"batch_cancelled", "batch_canceled"}:
        return "cancelled"
    return "failed"


def _normalize_input_part(part: Any) -> dict[str, str] | None:
    """Convert Pollux parts into OpenAI Responses API content parts."""
    if isinstance(part, str):
        return {"type": "input_text", "text": part}

    if isinstance(part, ProviderFileAsset):
        if part.provider != "openai":
            raise APIError(f"OpenAI cannot use {part.provider} file assets.")

        if part.is_inline_fallback:
            encoded_text = part.file_id
            if not encoded_text:
                raise APIError("Invalid OpenAI text asset: missing content payload")
            try:
                text = base64.urlsafe_b64decode(encoded_text.encode("ascii")).decode(
                    "utf-8"
                )
            except Exception as e:
                raise APIError(
                    "Invalid OpenAI text asset: malformed content payload"
                ) from e
            return {"type": "input_text", "text": text}

        file_id = part.file_id
        if not file_id:
            raise APIError("Invalid OpenAI file asset: missing file id")
        if part.mime_type.startswith("image/"):
            return {"type": "input_image", "file_id": file_id}
        return {"type": "input_file", "file_id": file_id}

    if not isinstance(part, dict):
        return None

    uri = part.get("uri")
    mime_type = part.get("mime_type")
    if not isinstance(uri, str) or not isinstance(mime_type, str):
        return None

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
