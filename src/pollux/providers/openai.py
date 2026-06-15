"""OpenAI provider implementation."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from pollux.errors import APIError, ConfigurationError
from pollux.parts import build_shared_parts
from pollux.providers import _compile
from pollux.providers._errors import wrap_provider_error
from pollux.providers._utils import (
    jsonable_provider_artifact,
    merge_provider_options,
    to_strict_schema,
)
from pollux.providers.base import (
    DeferredItemStatus,
    ProviderCapabilities,
    ProviderDeferredHandle,
    ProviderDeferredItem,
    ProviderDeferredSnapshot,
)
from pollux.providers.models import (
    ProviderFileAsset,
    ProviderResponse,
    ToolCall,
    is_file_part,
    provider_response_to_dict,
)

if TYPE_CHECKING:
    from pollux.config import Config
    from pollux.interaction.environment import EnvironmentSnapshot
    from pollux.interaction.input import Input
    from pollux.interaction.requirements import OutputRequirements

logger = logging.getLogger(__name__)


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
    def _validate_request_features(requirements: OutputRequirements) -> None:
        """Reject unsupported request features before any provider side effects."""
        if requirements.reasoning_budget_tokens is not None:
            raise ConfigurationError(
                "Provider does not support reasoning_budget_tokens",
                hint=(
                    "Use reasoning_effort, or choose a provider that accepts "
                    "an explicit reasoning token budget."
                ),
            )

    async def validate_request(
        self,
        snapshot: EnvironmentSnapshot,  # noqa: ARG002
        input: Input,  # noqa: A002, ARG002
        requirements: OutputRequirements,
        config: Config,  # noqa: ARG002
    ) -> None:
        """Validate OpenAI-specific request constraints."""
        self._validate_request_features(requirements)

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
            in_details = _field(usage_raw, "input_tokens_details")
            if in_details:
                cached_toks = _field(in_details, "cached_tokens")
                if cached_toks is not None:
                    usage["cached_tokens"] = int(cached_toks)

        tool_calls: list[ToolCall] = []
        reasoning_parts: list[str] = []
        annotations: list[Any] = []
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
            elif item_type == "message":
                for content in _field(item, "content", []) or []:
                    content_annotations = _field(content, "annotations", []) or []
                    if isinstance(content_annotations, list):
                        annotations.extend(content_annotations)

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
            artifacts=(
                {"annotations": jsonable_provider_artifact(annotations)}
                if annotations
                else None
            ),
        )

    async def submit_deferred(
        self,
        snapshot: EnvironmentSnapshot,
        inputs: list[Input],
        requirements: OutputRequirements,
        config: Config,
        *,
        request_ids: list[str],
    ) -> ProviderDeferredHandle:
        """Submit deferred work through the OpenAI Batch API."""
        client = self._get_client()

        try:
            lines: list[str] = []
            upload_cache: dict[tuple[str, str], ProviderFileAsset] = {}
            for request_id, inp in zip(request_ids, inputs, strict=True):
                body = await self._build_batch_request_body(
                    snapshot,
                    inp,
                    requirements,
                    config,
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
            batch_file_id = _field(batch_file, "id")
            has_schema = "1" if requirements.output_schema_json() is not None else "0"
            batch = await client.batches.create(
                input_file_id=batch_file.id,
                endpoint="/v1/responses",
                completion_window="24h",
                metadata={
                    "pollux_request_count": str(len(inputs)),
                    "pollux_has_response_schema": has_schema,
                },
            )
            return ProviderDeferredHandle(
                job_id=batch.id,
                submitted_at=float(batch.created_at),
                provider_state={
                    "request_ids": list(request_ids),
                    "owned_file_ids": _owned_batch_file_ids(
                        upload_cache,
                        batch_file_id=batch_file_id,
                    ),
                },
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

    async def inspect_deferred(
        self, handle: ProviderDeferredHandle
    ) -> ProviderDeferredSnapshot:
        """Inspect an OpenAI batch and normalize status/counts."""
        client = self._get_client()
        job_id = handle.job_id
        status: str | None = None

        try:
            batch = await client.batches.retrieve(job_id)
            raw_status = _field(batch, "status")
            total = _batch_total_requests(batch)
            completed = _batch_completed_requests(batch)
            failed = _batch_failed_requests(batch)
            status = _normalize_batch_status(
                raw_status,
                completed=completed,
                failed=failed,
            )
            failed, pending = _normalize_terminal_batch_counts(
                raw_status,
                total=total,
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
        finally:
            if status in {"completed", "partial", "failed", "cancelled", "expired"}:
                await self._cleanup_deferred_owned_files(handle)

    async def collect_deferred(
        self, handle: ProviderDeferredHandle
    ) -> list[ProviderDeferredItem]:
        """Collect OpenAI batch output and error files into deferred items."""
        client = self._get_client()
        job_id = handle.job_id

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

            synthesized = self._synthesize_terminal_batch_failure_items(
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
                provider="openai",
                phase="batch_collect",
                allow_network_errors=True,
                message="OpenAI batch collect failed",
            ) from e

    async def cancel_deferred(self, handle: ProviderDeferredHandle) -> None:
        """Cancel an OpenAI batch."""
        client = self._get_client()
        job_id = handle.job_id
        try:
            batch = await client.batches.cancel(job_id)
            status = _normalize_batch_status(
                _field(batch, "status"),
                completed=0,
                failed=0,
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
                provider="openai",
                phase="batch_cancel",
                allow_network_errors=True,
                message="OpenAI batch cancel failed",
            ) from e

    async def generate(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> ProviderResponse:
        """Generate a response using OpenAI's responses endpoint."""
        client = self._get_client()
        parts = _compile.request_parts(snapshot, input)
        create_kwargs = self._build_responses_create_kwargs(
            parts, snapshot, input, requirements, config
        )

        response = await client.responses.create(**create_kwargs)
        return self._parse_response(
            response, response_schema=requirements.output_schema_json()
        )

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

    async def _cleanup_deferred_owned_files(
        self, handle: ProviderDeferredHandle
    ) -> None:
        """Best-effort cleanup for provider-owned input files after terminal batches."""
        for file_id in _provider_handle_owned_file_ids(handle):
            try:
                await self.delete_file(file_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("OpenAI deferred cleanup failed for file_id=%s", file_id)

    def _build_responses_create_kwargs(
        self,
        parts: list[Any],
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
    ) -> dict[str, Any]:
        """Build the raw `/v1/responses` request body."""
        self._validate_request_features(requirements)

        history, previous_response_id, _provider_state = _compile.prior_turns(input)
        input_messages = self._build_input(parts, history, previous_response_id)

        create_kwargs: dict[str, Any] = {
            "model": config.model,
            "input": input_messages,
        }
        if requirements.temperature is not None:
            create_kwargs["temperature"] = requirements.temperature
        if requirements.top_p is not None:
            create_kwargs["top_p"] = requirements.top_p
        if requirements.max_tokens is not None:
            create_kwargs["max_output_tokens"] = requirements.max_tokens

        tools = _compile.tool_dicts(snapshot)
        if tools is not None:
            create_kwargs["tools"] = self._normalize_tools(tools)
            mapped = self._map_tool_choice(requirements.tool_choice)
            if mapped is not None:
                create_kwargs["tool_choice"] = mapped

        system_instruction = _compile.system_instruction(snapshot)
        if system_instruction:
            create_kwargs["instructions"] = system_instruction
        if previous_response_id:
            create_kwargs["previous_response_id"] = previous_response_id
        if requirements.reasoning_effort is not None:
            create_kwargs["reasoning"] = {
                "effort": requirements.reasoning_effort,
                "summary": "auto",
            }
        response_schema = requirements.output_schema_json()
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

        merge_provider_options(
            create_kwargs,
            requirements.provider_options_for("openai"),
            provider="openai",
        )
        return create_kwargs

    async def _build_batch_request_body(
        self,
        snapshot: EnvironmentSnapshot,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        requirements: OutputRequirements,
        config: Config,
        *,
        upload_cache: dict[tuple[str, str], ProviderFileAsset],
    ) -> dict[str, Any]:
        """Build one OpenAI Batch API line body for `/v1/responses`.

        Deferred submission resolves source uploads here (the snapshot is not
        pre-prepared for the batch path), then reuses the realtime request
        builder with the resolved parts.
        """
        self._validate_request_features(requirements)
        resolved_parts: list[Any] = []
        for part in build_shared_parts(snapshot.sources, provider=config.provider):
            if is_file_part(part):
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
        if input.content is not None:
            resolved_parts.append(input.content)

        return self._build_responses_create_kwargs(
            resolved_parts, snapshot, input, requirements, config
        )

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
                    response=provider_response_to_dict(parsed),
                    provider_status=_field(body, "status"),
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

    def _synthesize_terminal_batch_failure_items(
        self,
        batch: Any,
        *,
        handle: ProviderDeferredHandle,
        existing_request_ids: set[str],
    ) -> list[ProviderDeferredItem] | None:
        """Expand missing terminal items into per-request deferred diagnostics."""
        item_status = _batch_level_item_status(_field(batch, "status"))
        if item_status is None:
            return None

        request_ids = _provider_handle_request_ids(handle) or _batch_request_ids(batch)
        if not request_ids:
            return None
        missing_request_ids = [
            request_id
            for request_id in request_ids
            if request_id not in existing_request_ids
        ]
        if not missing_request_ids:
            return None

        error_message = _batch_error_message(batch)
        provider_status = _batch_error_code(batch) or str(_field(batch, "status", ""))
        return [
            ProviderDeferredItem(
                request_id=request_id,
                status=item_status,
                error=error_message,
                provider_status=provider_status or None,
            )
            for request_id in missing_request_ids
        ]


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


def _normalize_terminal_batch_counts(
    status: Any,
    *,
    total: int,
    completed: int,
    failed: int,
) -> tuple[int, int]:
    """Normalize terminal counts when OpenAI omits per-request failure totals."""
    pending = max(total - completed - failed, 0)
    if not isinstance(status, str):
        return failed, pending
    if status.lower() not in {"failed", "cancelled", "expired"}:
        return failed, pending
    return failed + pending, 0


def _batch_request_ids(batch: Any) -> list[str]:
    """Rebuild Pollux request ids from stored batch metadata."""
    total = _batch_total_requests(batch)
    return [f"pollux-{idx:06d}" for idx in range(total)]


def _owned_batch_file_ids(
    upload_cache: dict[tuple[str, str], ProviderFileAsset],
    *,
    batch_file_id: Any,
) -> list[str]:
    """Return provider-owned remote file ids created during batch submission."""
    file_ids = {
        asset.file_id
        for asset in upload_cache.values()
        if asset.file_id and not asset.is_inline_fallback
    }
    if isinstance(batch_file_id, str) and batch_file_id:
        file_ids.add(batch_file_id)
    return sorted(file_ids)


def _provider_handle_request_ids(handle: ProviderDeferredHandle) -> list[str] | None:
    """Return the authoritative submitted request ids stored in the handle."""
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

    file_ids: list[str] = []
    for value in raw_ids:
        if isinstance(value, str) and value:
            file_ids.append(value)
    return file_ids


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
        return "partial" if completed > 0 or failed > 0 else "cancelled"
    if raw == "expired":
        return "partial" if completed > 0 or failed > 0 else "expired"
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


def _batch_error_entries(batch: Any) -> list[Any]:
    """Return batch-level validation/runtime errors when present."""
    errors = _field(batch, "errors")
    data = _field(errors, "data") if errors is not None else None
    return data if isinstance(data, list) else []


def _batch_error_message(batch: Any) -> str | None:
    """Return a readable message for batch-level failures without item files."""
    messages: list[str] = []
    for entry in _batch_error_entries(batch):
        message = _field(entry, "message")
        if isinstance(message, str) and message and message not in messages:
            messages.append(message)
    if messages:
        return "; ".join(messages)
    return None


def _batch_error_code(batch: Any) -> str | None:
    """Return the first batch-level error code when present."""
    for entry in _batch_error_entries(batch):
        code = _field(entry, "code")
        if isinstance(code, str) and code:
            return code
    return None


def _error_message(error: Any) -> str | None:
    """Best-effort message extraction from OpenAI batch error payloads."""
    if isinstance(error, dict):
        nested = error.get("error")
        if isinstance(nested, dict):
            nested_message = _error_message(nested)
            if nested_message is not None:
                return nested_message
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


def _batch_level_item_status(status: Any) -> DeferredItemStatus | None:
    """Map batch terminal status into a per-item fallback status."""
    if not isinstance(status, str):
        return None
    if status == "failed":
        return "failed"
    if status == "cancelled":
        return "cancelled"
    if status == "expired":
        return "expired"
    return None


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

    if _is_openai_remote_file_mime_type(mime_type):
        return {"type": "input_file", "file_url": uri}
    if mime_type.startswith("image/"):
        return {"type": "input_image", "image_url": uri}

    raise APIError(
        f"Unsupported remote mime type for OpenAI provider: {mime_type}",
        hint=(
            "Supported remote types are images plus text, PDF, and common "
            "document/spreadsheet/presentation file URLs."
        ),
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


def _is_openai_remote_file_mime_type(mime_type: str) -> bool:
    """Return True when OpenAI can receive a remote URL as input_file."""
    if _is_text_like_mime_type(mime_type):
        return True
    common_document_types = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/rtf",
    }
    return mime_type in common_document_types
