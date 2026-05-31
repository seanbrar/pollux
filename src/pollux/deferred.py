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
    ValidatingProvider,
)
from pollux.providers.models import (
    ProviderRequest,
    ProviderResponse,
    ToolCall,
    is_file_part,
)
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
    # Two distinct instance-level gates (see also the pre-instantiation registry
    # gate in __init__._resolve_deferred_provider):
    #  - the capability flag is the user-facing "not supported" contract;
    #  - the protocol check verifies the declaration matches the implementation,
    #    so a flag set without the lifecycle methods is a programming error.
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

    if options.delivery_mode == "deferred":
        raise ConfigurationError(
            "delivery_mode='deferred' is not needed with defer() or defer_many()",
            hint="Call defer() / defer_many() directly without setting delivery_mode.",
        )

    _get_deferred_provider(provider)
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
            hint=(
                "Remove reasoning_effort or choose a provider with reasoning "
                "controls. Some providers may still surface model-native "
                "reasoning output without this option."
            ),
        )
    if options.reasoning_budget_tokens is not None and not caps.reasoning_budget_tokens:
        raise ConfigurationError(
            "Provider does not support reasoning_budget_tokens",
            hint=(
                "Use reasoning_effort, or choose a provider that accepts "
                "an explicit reasoning token budget."
            ),
        )
    if (not caps.uploads) and any(is_file_part(part) for part in plan.shared_parts):
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
                reasoning_budget_tokens=options.reasoning_budget_tokens,
                max_tokens=options.max_tokens,
            )
        )
    return requests


async def _validate_provider_requests(
    provider: Provider,
    requests: list[ProviderRequest],
) -> None:
    """Run provider-owned validation before deferred submission side effects."""
    if not isinstance(provider, ValidatingProvider):
        return
    # TODO: parallelize if a future provider's validate_request does I/O
    # (e.g. OpenRouter-style metadata lookups). Current validators are local.
    for request in requests:
        await provider.validate_request(request)


async def submit_deferred(plan: Plan, provider: Provider) -> DeferredHandle:
    """Submit provider-backed deferred work and return the Pollux handle."""
    _validate_deferred_plan(plan, provider)
    requests = _build_provider_requests(plan)
    await _validate_provider_requests(provider, requests)
    deferred_provider = _get_deferred_provider(provider)
    request_ids = _request_ids(len(plan.request.prompts))
    provider_handle = await deferred_provider.submit_deferred(
        requests,
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


def _aggregate_usage(responses: list[ProviderResponse]) -> dict[str, int]:
    total_usage: dict[str, int] = {}
    for response in responses:
        for key, value in response.usage.items():
            if isinstance(value, int):
                total_usage[key] = total_usage.get(key, 0) + value
    return total_usage


def _response_from_item(item: ProviderDeferredItem) -> ProviderResponse:
    if item.status != "succeeded":
        return ProviderResponse(text="", usage={}, finish_reason=item.finish_reason)
    if item.response is None:
        raise InternalError(
            f"Deferred item {item.request_id!r} succeeded without a response payload",
            hint="Deferred providers must return a response for succeeded items.",
        )
    payload = item.response
    raw_text = payload.get("text", "")
    raw_usage = payload.get("usage")
    raw_tool_calls = payload.get("tool_calls")
    tool_calls: list[ToolCall] | None = None
    if isinstance(raw_tool_calls, list):
        tool_calls = [
            ToolCall(
                id=str(tc.get("id", "")),
                name=str(tc.get("name", "")),
                arguments=str(tc.get("arguments", "")),
            )
            for tc in raw_tool_calls
            if isinstance(tc, dict)
        ]
    return ProviderResponse(
        text=raw_text if isinstance(raw_text, str) else "",
        usage=raw_usage if isinstance(raw_usage, dict) else {},
        reasoning=payload.get("reasoning"),
        structured=payload.get("structured"),
        tool_calls=tool_calls,
        response_id=payload.get("response_id"),
        finish_reason=payload.get("finish_reason", item.finish_reason),
    )


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
    responses: list[ProviderResponse] = []
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
        response.structured is not None for response in responses
    ):
        result["structured"] = [response.structured for response in responses]

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
