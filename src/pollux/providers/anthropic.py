"""Anthropic Messages API provider."""

from __future__ import annotations

import asyncio
from datetime import datetime
import inspect
import json
import logging
from typing import TYPE_CHECKING, Any

from pollux.errors import APIError, ConfigurationError
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
    Message,
    ProviderFileAsset,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
)

if TYPE_CHECKING:
    from pathlib import Path

_ANTHROPIC_DEFAULT_MAX_TOKENS = 16384
logger = logging.getLogger(__name__)
_INTERLEAVED_THINKING_BETA_HEADER = "interleaved-thinking-2025-05-14"
_ANTHROPIC_THINKING_BLOCKS_KEY = "anthropic_thinking_blocks"
_ALLOWED_REASONING_EFFORTS = {"low", "medium", "high", "max"}
# Note: Sonnet 4.6 supports both manual and adaptive thinking.
# We route through adaptive as it is the recommended path and simpler UX.
_ADAPTIVE_THINKING_MODEL_PREFIXES = ("claude-opus-4-6", "claude-sonnet-4-6")
_MANUAL_THINKING_BUDGETS = {
    "low": 2048,
    "medium": 5120,
    "high": 10240,
    "max": 12288,
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
    def capabilities(self) -> ProviderCapabilities:
        """Return supported feature flags."""
        return ProviderCapabilities(
            persistent_cache=False,
            uploads=True,
            structured_outputs=True,
            reasoning=True,
            deferred_delivery=True,
            conversation=True,
            implicit_caching=True,
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

    def _build_messages_create_kwargs(self, request: ProviderRequest) -> dict[str, Any]:
        """Build the raw Anthropic Messages API request body."""
        # No Anthropic equivalents or deferred features.
        _ = request.cache_name
        _ = request.previous_response_id

        messages = self._build_messages(
            request.parts,
            request.history,
            request.provider_state,
        )

        default_max_tokens = _ANTHROPIC_DEFAULT_MAX_TOKENS
        if "claude-3-" in request.model:
            # claude-3-haiku, claude-3-sonnet, claude-3-opus only support 4096
            default_max_tokens = 4096
            if "claude-3-5" in request.model:
                default_max_tokens = 8192

        create_kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": (
                request.max_tokens
                if request.max_tokens is not None
                else default_max_tokens
            ),
        }

        if request.implicit_caching:
            create_kwargs["cache_control"] = {"type": "ephemeral"}

        if request.system_instruction:
            create_kwargs["system"] = request.system_instruction

        if request.temperature is not None:
            create_kwargs["temperature"] = request.temperature
        if request.top_p is not None:
            create_kwargs["top_p"] = request.top_p

        if request.tools is not None:
            anthropic_tools = self._normalize_tools(request.tools)
            if anthropic_tools:
                create_kwargs["tools"] = anthropic_tools

            mapped = self._map_tool_choice(request.tool_choice)
            if mapped is not None:
                create_kwargs["tool_choice"] = mapped

        output_config: dict[str, Any] = {}

        if request.response_schema is not None:
            strict_schema = to_strict_schema(request.response_schema)
            output_config["format"] = {
                "type": "json_schema",
                "schema": strict_schema,
            }

        if request.reasoning_effort is not None:
            effort = _normalize_reasoning_effort(
                request.reasoning_effort, request.model
            )
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

        beta_headers = ["files-api-2025-04-14"]
        extra_headers = create_kwargs.get("extra_headers")
        if isinstance(extra_headers, dict):
            existing_beta = extra_headers.get("anthropic-beta")
            if isinstance(existing_beta, str) and existing_beta:
                beta_headers.append(existing_beta)
        create_kwargs["extra_headers"] = {"anthropic-beta": ",".join(beta_headers)}

        return create_kwargs

    async def submit_deferred(
        self,
        requests: list[ProviderRequest],
        *,
        request_ids: list[str],
    ) -> ProviderDeferredHandle:
        """Submit deferred work through the Anthropic Message Batches API."""
        client = self._get_client()

        try:
            upload_cache: dict[tuple[str, str], ProviderFileAsset] = {}
            batch_requests: list[dict[str, Any]] = []
            for request_id, request in zip(request_ids, requests, strict=True):
                resolved_request = await self._resolve_deferred_request(
                    request,
                    upload_cache=upload_cache,
                )
                create_kwargs = self._build_messages_create_kwargs(resolved_request)
                create_kwargs.pop("extra_headers", None)
                batch_requests.append(
                    {
                        "custom_id": request_id,
                        "params": create_kwargs,
                    }
                )

            batch = await client.messages.batches.create(
                requests=batch_requests,
                extra_headers={"anthropic-beta": "files-api-2025-04-14"},
            )
            return ProviderDeferredHandle(
                job_id=batch.id,
                submitted_at=_timestamp_or_none(batch.created_at),
                provider_state={
                    "request_ids": list(request_ids),
                    "owned_file_ids": _owned_deferred_file_ids(upload_cache),
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
                provider="anthropic",
                phase="batch_submit",
                allow_network_errors=False,
                message="Anthropic batch submit failed",
            ) from e

    async def inspect_deferred(
        self, handle: ProviderDeferredHandle
    ) -> ProviderDeferredSnapshot:
        """Inspect an Anthropic message batch and normalize status/counts."""
        client = self._get_client()
        status: str | None = None

        try:
            batch = await client.messages.batches.retrieve(handle.job_id)
            total = _batch_request_count(batch, handle=handle)
            succeeded = int(getattr(batch.request_counts, "succeeded", 0))
            failed = int(
                getattr(batch.request_counts, "errored", 0)
                + getattr(batch.request_counts, "canceled", 0)
                + getattr(batch.request_counts, "expired", 0)
            )
            pending = int(getattr(batch.request_counts, "processing", 0))
            status = _normalize_batch_status(
                batch.processing_status,
                succeeded=succeeded,
                errored=int(getattr(batch.request_counts, "errored", 0)),
                canceled=int(getattr(batch.request_counts, "canceled", 0)),
                expired=int(getattr(batch.request_counts, "expired", 0)),
                total=total,
            )
            return ProviderDeferredSnapshot(
                status=status,
                provider_status=str(batch.processing_status),
                request_count=total,
                succeeded=succeeded,
                failed=failed,
                pending=pending,
                submitted_at=_timestamp_or_none(batch.created_at),
                completed_at=_timestamp_or_none(batch.ended_at),
                expires_at=_timestamp_or_none(batch.expires_at),
            )
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="anthropic",
                phase="batch_inspect",
                allow_network_errors=True,
                message="Anthropic batch inspect failed",
            ) from e
        finally:
            if status in {"completed", "partial", "failed", "cancelled", "expired"}:
                await self._cleanup_deferred_owned_files(handle)

    async def collect_deferred(
        self, handle: ProviderDeferredHandle
    ) -> list[ProviderDeferredItem]:
        """Collect Anthropic batch results into deferred items."""
        client = self._get_client()

        try:
            batch = await client.messages.batches.retrieve(handle.job_id)
            items: list[ProviderDeferredItem] = []
            if batch.results_url is not None:
                results_stream = client.messages.batches.results(handle.job_id)
                if inspect.isawaitable(results_stream):
                    results_stream = await results_stream
                async for row in results_stream:
                    items.append(
                        _parse_batch_result(
                            row,
                            parse_structured_json=_provider_handle_has_response_schema(
                                handle
                            ),
                        )
                    )

            synthesized = _synthesize_terminal_batch_items(
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
                provider="anthropic",
                phase="batch_collect",
                allow_network_errors=True,
                message="Anthropic batch collect failed",
            ) from e

    async def cancel_deferred(self, handle: ProviderDeferredHandle) -> None:
        """Cancel an Anthropic message batch."""
        client = self._get_client()

        try:
            batch = await client.messages.batches.cancel(handle.job_id)
            status = _normalize_batch_status(
                batch.processing_status,
                succeeded=int(getattr(batch.request_counts, "succeeded", 0)),
                errored=int(getattr(batch.request_counts, "errored", 0)),
                canceled=int(getattr(batch.request_counts, "canceled", 0)),
                expired=int(getattr(batch.request_counts, "expired", 0)),
                total=_batch_request_count(batch, handle=handle),
            )
            if status in {"completed", "partial", "failed", "cancelled", "expired"}:
                await self._cleanup_deferred_owned_files(handle)
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="anthropic",
                phase="batch_cancel",
                allow_network_errors=True,
                message="Anthropic batch cancel failed",
            ) from e

    async def generate(
        self,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """Generate a response using Anthropic's Messages API."""
        client = self._get_client()
        create_kwargs = self._build_messages_create_kwargs(request)

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

    async def upload_file(self, path: Path, mime_type: str) -> ProviderFileAsset:
        """Upload a local file using the Anthropic Files API."""
        client = self._get_client()

        try:
            with path.open("rb") as f:
                result = await client.beta.files.upload(
                    file=(path.name, f.read(), mime_type),
                    extra_headers={"anthropic-beta": "files-api-2025-04-14"},
                )

            return ProviderFileAsset(
                file_id=result.id,
                provider="anthropic",
                mime_type=mime_type,
                file_name=result.id,
            )
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except Exception as e:
            raise wrap_provider_error(
                e,
                provider="anthropic",
                phase="upload",
                allow_network_errors=False,
                message="Anthropic upload failed",
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
        """Raise because Anthropic caching is deferred."""
        _ = model, parts, system_instruction, tools, ttl_seconds
        raise APIError("Anthropic provider does not support context caching")

    async def delete_file(self, file_id: str) -> None:
        """Delete a previously uploaded file from Anthropic storage."""
        client = self._get_client()
        await client.beta.files.delete(
            file_id,
            extra_headers={"anthropic-beta": "files-api-2025-04-14"},
        )

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
                logger.debug(
                    "Anthropic deferred cleanup failed for file_id=%s", file_id
                )

    async def aclose(self) -> None:
        """Close underlying async client resources."""
        client = self._client
        if client is None:
            return
        self._client = None
        await client.close()


def _parse_response(
    response: Any,
    *,
    response_schema: dict[str, Any] | None,
    parse_structured_json: bool = False,
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
    if (response_schema is not None or parse_structured_json) and text:
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


def _provider_handle_has_response_schema(handle: ProviderDeferredHandle) -> bool:
    """Return True when structured outputs were enabled at submission time."""
    provider_state = handle.provider_state
    if not isinstance(provider_state, dict):
        return False
    return bool(provider_state.get("has_response_schema"))


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


def _batch_request_count(batch: Any, *, handle: ProviderDeferredHandle) -> int:
    """Return the total request count for an Anthropic message batch."""
    request_counts = getattr(batch, "request_counts", None)
    if request_counts is not None:
        return int(
            getattr(request_counts, "succeeded", 0)
            + getattr(request_counts, "errored", 0)
            + getattr(request_counts, "canceled", 0)
            + getattr(request_counts, "expired", 0)
            + getattr(request_counts, "processing", 0)
        )
    request_ids = _provider_handle_request_ids(handle)
    return len(request_ids) if request_ids is not None else 0


def _normalize_batch_status(
    processing_status: str,
    *,
    succeeded: int,
    errored: int,
    canceled: int,
    expired: int,
    total: int,
) -> str:
    """Map Anthropic message batch state into Pollux deferred statuses."""
    if processing_status == "in_progress":
        return "running"
    if processing_status == "canceling":
        return "cancelling"

    if succeeded == total and total > 0:
        return "completed"
    if succeeded > 0:
        return "partial"
    if errored == total and total > 0:
        return "failed"
    if canceled == total and total > 0:
        return "cancelled"
    if expired == total and total > 0:
        return "expired"
    if errored > 0 and canceled == 0 and expired == 0:
        return "failed"
    if canceled > 0 and errored == 0 and expired == 0:
        return "cancelled"
    if expired > 0 and errored == 0 and canceled == 0:
        return "expired"
    if errored > 0 or canceled > 0 or expired > 0:
        return "partial"
    return "failed"


def _parse_batch_result(
    row: Any,
    *,
    parse_structured_json: bool,
) -> ProviderDeferredItem:
    """Parse one Anthropic batch result row into a deferred item."""
    request_id = str(row.custom_id)
    result = row.result
    result_type = str(getattr(result, "type", ""))

    if result_type == "succeeded":
        parsed = _parse_response(
            result.message,
            response_schema=None,
            parse_structured_json=parse_structured_json,
        )
        return ProviderDeferredItem(
            request_id=request_id,
            status="succeeded",
            response=_provider_response_to_dict(parsed),
            provider_status="succeeded",
            finish_reason=parsed.finish_reason,
        )

    if result_type == "errored":
        error = getattr(result, "error", None)
        return ProviderDeferredItem(
            request_id=request_id,
            status="failed",
            error=_anthropic_error_message(error),
            provider_status=_anthropic_error_type(error),
        )

    if result_type == "canceled":
        return ProviderDeferredItem(
            request_id=request_id,
            status="cancelled",
            provider_status="canceled",
        )

    if result_type == "expired":
        return ProviderDeferredItem(
            request_id=request_id,
            status="expired",
            provider_status="expired",
        )

    raise APIError(f"Unsupported Anthropic batch result type: {result_type}")


def _anthropic_error_message(error: Any) -> str | None:
    """Return a readable message for Anthropic error payloads."""
    message = getattr(error, "message", None)
    return message if isinstance(message, str) and message else None


def _anthropic_error_type(error: Any) -> str | None:
    """Return the Anthropic error type when present."""
    error_type = getattr(error, "type", None)
    return error_type if isinstance(error_type, str) and error_type else None


def _batch_level_item_status(batch: Any) -> DeferredItemStatus | None:
    """Return a synthesized item status for missing terminal Anthropic rows."""
    if str(getattr(batch, "processing_status", "")) != "ended":
        return None

    request_counts = getattr(batch, "request_counts", None)
    if request_counts is None:
        return None

    succeeded = int(getattr(request_counts, "succeeded", 0))
    errored = int(getattr(request_counts, "errored", 0))
    canceled = int(getattr(request_counts, "canceled", 0))
    expired = int(getattr(request_counts, "expired", 0))

    if succeeded > 0:
        if errored > 0 and canceled == 0 and expired == 0:
            return "failed"
        if canceled > 0 and errored == 0 and expired == 0:
            return "cancelled"
        if expired > 0 and errored == 0 and canceled == 0:
            return "expired"
        return None
    if errored > 0 and canceled == 0 and expired == 0:
        return "failed"
    if canceled > 0 and errored == 0 and expired == 0:
        return "cancelled"
    if expired > 0 and errored == 0 and canceled == 0:
        return "expired"
    if errored > 0 or canceled > 0 or expired > 0:
        return "failed"
    return None


def _synthesize_terminal_batch_items(
    batch: Any,
    *,
    handle: ProviderDeferredHandle,
    existing_request_ids: set[str],
) -> list[ProviderDeferredItem] | None:
    """Expand missing terminal Anthropic rows into per-request diagnostics."""
    item_status = _batch_level_item_status(batch)
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

    provider_status = str(getattr(batch, "processing_status", "ended"))
    return [
        ProviderDeferredItem(
            request_id=request_id,
            status=item_status,
            provider_status=provider_status,
        )
        for request_id in missing_request_ids
    ]


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


def _normalize_reasoning_effort(reasoning_effort: str, model_name: str) -> str:
    """Normalize and validate Anthropic effort values."""
    effort = reasoning_effort.strip().lower()
    if effort not in _ALLOWED_REASONING_EFFORTS:
        allowed = ", ".join(sorted(_ALLOWED_REASONING_EFFORTS))
        raise APIError(
            f"Unsupported reasoning_effort for Anthropic: {reasoning_effort!r}",
            hint=f"Use one of: {allowed}.",
        )

    if effort == "max" and not model_name.lower().startswith("claude-opus-4-6"):
        raise ConfigurationError(
            "reasoning_effort='max' is only supported on Claude Opus 4.6.",
            hint="Try 'high' for this model.",
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

    if isinstance(part, ProviderFileAsset):
        if part.provider != "anthropic":
            raise APIError(f"Cannot use {part.provider} asset with Anthropic provider.")
        uri = part.file_id
        if not isinstance(uri, str):
            raise APIError(
                f"Anthropic provider expects string file_id, got {type(uri)}"
            )
        mime_type = part.mime_type
        if not isinstance(mime_type, str):
            raise APIError(
                f"Anthropic provider expects string mime_type, got {type(mime_type)}"
            )
        # Anthropic Files API requires 'source' for assets
        if mime_type.startswith("image/"):
            return {
                "type": "image",
                "source": {
                    "type": "file",
                    "file_id": uri,
                },
            }
        if mime_type == "application/pdf" or mime_type.startswith("text/"):
            return {
                "type": "document",
                "source": {
                    "type": "file",
                    "file_id": uri,
                },
            }
        raise APIError(
            f"Unsupported mime type for Anthropic Files API: {mime_type}",
            hint="Anthropic supports text, images and PDFs via file IDs.",
        )

    if not isinstance(part, dict):
        return None

    dict_uri = part.get("uri")
    dict_mime_type = part.get("mime_type")

    # Mypy requires explicit string inference over Any
    if not isinstance(dict_uri, str) or not isinstance(dict_mime_type, str):
        return None

    # Image URL support.
    if dict_mime_type.startswith("image/"):
        return {
            "type": "image",
            "source": {
                "type": "url",
                "url": dict_uri,
            },
        }

    # PDF support via document blocks.
    if dict_mime_type == "application/pdf":
        return {
            "type": "document",
            "source": {
                "type": "url",
                "url": dict_uri,
            },
        }

    raise APIError(
        f"Unsupported mime type for Anthropic provider: {dict_mime_type}",
        hint="Anthropic supports images and PDFs via URL.",
    )
