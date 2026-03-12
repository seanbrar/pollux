"""Deferred delivery public types and provider-backed lifecycle helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import time
from typing import TYPE_CHECKING, Any, Literal, cast

from pollux.errors import ConfigurationError, DeferredNotReadyError, InternalError
from pollux.options import (
    ResponseSchemaInput,
    response_schema_hash,
)
from pollux.providers.base import (
    DeferredProvider,
    Provider,
    ProviderDeferredHandle,
    ProviderDeferredItem,
    ProviderDeferredSnapshot,
)
from pollux.providers.models import ProviderRequest
from pollux.result import build_result_from_responses

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pollux.plan import Plan
    from pollux.result import ResultEnvelope

DeferredStatus = Literal[
    "queued",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelling",
    "cancelled",
    "expired",
]

_TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled", "expired"}


@dataclass(frozen=True)
class DeferredHandle:
    """Serializable Pollux handle for a deferred job."""

    job_id: str
    provider: str
    model: str
    request_count: int
    submitted_at: float
    schema_hash: str | None = None
    provider_state: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the handle for persistence."""
        return dict(asdict(self))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DeferredHandle:
        """Rebuild a handle from serialized data."""
        return cls(
            job_id=str(data["job_id"]),
            provider=str(data["provider"]),
            model=str(data["model"]),
            request_count=int(data["request_count"]),
            submitted_at=float(data["submitted_at"]),
            schema_hash=(
                None
                if data.get("schema_hash") is None
                else str(data.get("schema_hash"))
            ),
            provider_state=(
                dict(data["provider_state"])
                if isinstance(data.get("provider_state"), dict)
                else None
            ),
        )


@dataclass(frozen=True)
class DeferredSnapshot:
    """Normalized snapshot of a deferred job lifecycle."""

    job_id: str
    provider: str
    model: str
    status: DeferredStatus
    provider_status: str
    request_count: int
    succeeded: int
    failed: int
    pending: int
    submitted_at: float
    completed_at: float | None = None
    expires_at: float | None = None

    @property
    def is_terminal(self) -> bool:
        """Return True when the job is ready to collect or permanently done."""
        return self.status in _TERMINAL_STATUSES


def _get_deferred_provider(provider: Provider) -> DeferredProvider:
    if not provider.capabilities.deferred_delivery:
        raise ConfigurationError(
            "Provider does not support deferred delivery",
            hint="Choose a provider with deferred delivery support.",
        )
    if not isinstance(provider, DeferredProvider):
        raise InternalError(
            "Provider advertises deferred delivery but does not implement the deferred lifecycle protocol",
            hint="Implement DeferredProvider for this provider.",
        )
    return provider


def _request_ids(count: int) -> list[str]:
    return [f"pollux-{idx:06d}" for idx in range(count)]


def _provider_handle_from_handle(handle: DeferredHandle) -> ProviderDeferredHandle:
    """Rebuild the provider-facing deferred handle from the public Pollux handle."""
    return ProviderDeferredHandle(
        job_id=handle.job_id,
        submitted_at=handle.submitted_at,
        provider_state=(
            dict(handle.provider_state)
            if isinstance(handle.provider_state, dict)
            else None
        ),
    )


def _validate_deferred_plan(plan: Plan, provider: Provider) -> None:
    options = plan.request.options
    caps = provider.capabilities

    _get_deferred_provider(provider)

    if options.delivery_mode == "deferred":
        raise ConfigurationError(
            "delivery_mode='deferred' is not needed with defer() or defer_many()",
            hint="Call defer() / defer_many() directly without setting delivery_mode.",
        )
    if options.cache is not None:
        raise ConfigurationError(
            "Persistent cache handles are not supported with deferred delivery",
            hint="Remove options.cache for deferred requests.",
        )
    if options.history is not None or options.continue_from is not None:
        raise ConfigurationError(
            "Conversation continuity is not supported with deferred delivery",
            hint="Remove history/continue_from or use run().",
        )
    if options.tools is not None or options.tool_choice is not None:
        raise ConfigurationError(
            "Tool calling is not supported with deferred delivery",
            hint="Remove tools/tool_choice or use run().",
        )
    if options.implicit_caching is not None:
        raise ConfigurationError(
            "implicit_caching is not supported with deferred delivery",
            hint="Remove implicit_caching for deferred requests.",
        )
    if options.response_schema is not None and not caps.structured_outputs:
        raise ConfigurationError(
            "Provider does not support structured outputs",
            hint="Remove response_schema or choose a provider with schema support.",
        )
    if options.reasoning_effort is not None and not caps.reasoning:
        raise ConfigurationError(
            "Provider does not support reasoning controls",
            hint="Remove reasoning_effort or choose a provider with reasoning support.",
        )
    if (not caps.uploads) and any(
        isinstance(part, dict)
        and isinstance(part.get("file_path"), str)
        and isinstance(part.get("mime_type"), str)
        for part in plan.shared_parts
    ):
        raise ConfigurationError(
            "Provider does not support file uploads",
            hint="Choose a provider with uploads support, or remove file sources.",
        )


def _build_provider_requests(plan: Plan) -> list[ProviderRequest]:
    options = plan.request.options
    schema = options.response_schema_json()
    requests: list[ProviderRequest] = []
    for prompt in plan.request.prompts:
        parts = list(plan.shared_parts)
        if prompt is not None:
            parts.append(prompt)
        requests.append(
            ProviderRequest(
                model=plan.request.config.model,
                parts=parts,
                system_instruction=options.system_instruction,
                response_schema=schema,
                temperature=options.temperature,
                top_p=options.top_p,
                reasoning_effort=options.reasoning_effort,
                max_tokens=options.max_tokens,
            )
        )
    return requests


async def submit_deferred(plan: Plan, provider: Provider) -> DeferredHandle:
    """Submit provider-backed deferred work and return the Pollux handle."""
    _validate_deferred_plan(plan, provider)
    deferred_provider = _get_deferred_provider(provider)
    request_ids = _request_ids(len(plan.request.prompts))
    provider_handle = await deferred_provider.submit_deferred(
        _build_provider_requests(plan),
        request_ids=request_ids,
    )
    submitted_at = (
        provider_handle.submitted_at
        if provider_handle.submitted_at is not None
        else time.time()
    )
    return DeferredHandle(
        job_id=provider_handle.job_id,
        provider=plan.request.config.provider,
        model=plan.request.config.model,
        request_count=len(plan.request.prompts),
        submitted_at=submitted_at,
        schema_hash=plan.request.options.response_schema_hash(),
        provider_state=(
            dict(provider_handle.provider_state)
            if isinstance(provider_handle.provider_state, dict)
            else None
        ),
    )


def _snapshot_from_provider(
    handle: DeferredHandle,
    snapshot: ProviderDeferredSnapshot,
) -> DeferredSnapshot:
    status = cast("DeferredStatus", snapshot.status)
    submitted_at = (
        snapshot.submitted_at
        if snapshot.submitted_at is not None
        else handle.submitted_at
    )
    return DeferredSnapshot(
        job_id=handle.job_id,
        provider=handle.provider,
        model=handle.model,
        status=status,
        provider_status=snapshot.provider_status,
        request_count=snapshot.request_count,
        succeeded=snapshot.succeeded,
        failed=snapshot.failed,
        pending=snapshot.pending,
        submitted_at=submitted_at,
        completed_at=snapshot.completed_at,
        expires_at=snapshot.expires_at,
    )


async def inspect_deferred_handle(
    handle: DeferredHandle,
    provider: Provider,
) -> DeferredSnapshot:
    """Inspect a deferred job and return a normalized snapshot."""
    deferred_provider = _get_deferred_provider(provider)
    return _snapshot_from_provider(
        handle,
        await deferred_provider.inspect_deferred(_provider_handle_from_handle(handle)),
    )


def _validate_collect_schema(
    handle: DeferredHandle,
    response_schema: ResponseSchemaInput | None,
) -> None:
    if response_schema is None:
        return
    if handle.schema_hash is None:
        raise ConfigurationError(
            "response_schema was provided at collect time but no schema was used at submission",
            hint="Omit response_schema, or re-submit with Options(response_schema=...) to enable rehydration.",
        )
    current_hash = response_schema_hash(response_schema)
    if current_hash != handle.schema_hash:
        raise ConfigurationError(
            "response_schema does not match the schema used at deferred submission time",
            hint="Pass the same schema used with defer(), or omit response_schema to collect plain dicts.",
        )


def _aggregate_usage(responses: list[dict[str, Any]]) -> dict[str, int]:
    total_usage: dict[str, int] = {}
    for response in responses:
        usage = response.get("usage", {})
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(value, int):
                total_usage[key] = total_usage.get(key, 0) + value
    return total_usage


def _response_from_item(item: ProviderDeferredItem) -> dict[str, Any]:
    if item.status != "succeeded":
        response: dict[str, Any] = {"text": "", "usage": {}}
        if item.finish_reason is not None:
            response["finish_reason"] = item.finish_reason
        return response
    if item.response is None:
        raise InternalError(
            f"Deferred item {item.request_id!r} succeeded without a response payload",
            hint="Deferred providers must return a response for succeeded items.",
        )
    response = dict(item.response)
    response.setdefault("text", "")
    if "usage" not in response or not isinstance(response["usage"], dict):
        response["usage"] = {}
    if item.finish_reason is not None:
        response.setdefault("finish_reason", item.finish_reason)
    return response


async def collect_deferred_handle(
    handle: DeferredHandle,
    provider: Provider,
    *,
    response_schema: ResponseSchemaInput | None = None,
) -> ResultEnvelope:
    """Collect a terminal deferred job into a standard ResultEnvelope."""
    deferred_provider = _get_deferred_provider(provider)
    _validate_collect_schema(handle, response_schema)

    start_time = time.perf_counter()
    snapshot = await inspect_deferred_handle(handle, provider)
    if not snapshot.is_terminal:
        raise DeferredNotReadyError(snapshot)

    items = await deferred_provider.collect_deferred(
        _provider_handle_from_handle(handle)
    )
    items_by_id: dict[str, ProviderDeferredItem] = {}
    for item in items:
        if item.request_id in items_by_id:
            raise InternalError(
                f"Deferred provider returned duplicate request id {item.request_id!r}",
                hint="Deferred providers must return at most one collected item per request id.",
            )
        items_by_id[item.request_id] = item

    request_ids = _request_ids(handle.request_count)
    responses: list[dict[str, Any]] = []
    deferred_items: list[dict[str, Any]] = []
    for request_id in request_ids:
        collected_item = items_by_id.get(request_id)
        if collected_item is None:
            raise InternalError(
                f"Deferred provider did not return item {request_id!r}",
                hint="Deferred providers must return one item for every submitted request id.",
            )
        responses.append(_response_from_item(collected_item))
        deferred_items.append(
            {
                "request_id": request_id,
                "status": collected_item.status,
                "error": collected_item.error,
                "provider_status": collected_item.provider_status,
                "finish_reason": collected_item.finish_reason,
            }
        )

    usage = _aggregate_usage(responses)
    duration_s = time.perf_counter() - start_time

    result = build_result_from_responses(
        responses,
        schema=response_schema,
        duration_s=duration_s,
        usage=usage,
        n_calls=handle.request_count,
    )

    # When no schema was provided at collect time but providers returned
    # structured payloads, surface them as plain dicts.
    if response_schema is None and any(
        "structured" in response for response in responses
    ):
        result["structured"] = [response.get("structured") for response in responses]

    result["metrics"]["deferred"] = True
    result["diagnostics"]["deferred"] = {
        "job_id": handle.job_id,
        "submitted_at": snapshot.submitted_at,
        "completed_at": snapshot.completed_at,
        "elapsed_s": (
            None
            if snapshot.completed_at is None
            else snapshot.completed_at - snapshot.submitted_at
        ),
        "items": deferred_items,
    }
    return result


async def cancel_deferred_handle(handle: DeferredHandle, provider: Provider) -> None:
    """Request provider-side cancellation for a deferred job."""
    deferred_provider = _get_deferred_provider(provider)
    await deferred_provider.cancel_deferred(_provider_handle_from_handle(handle))
