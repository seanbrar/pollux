"""Deferred delivery public types and provider-backed lifecycle helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import time
from typing import TYPE_CHECKING, Any, Literal, cast

from pollux.errors import ConfigurationError, DeferredNotReadyError, InternalError
from pollux.interaction.capabilities import resolve_capabilities
from pollux.interaction.collection import OutputCollection
from pollux.interaction.environment import EnvironmentSnapshot
from pollux.interaction.extract import provider_response_to_output
from pollux.interaction.output import Diagnostics, Output
from pollux.interaction.requirements import OutputRequirements
from pollux.interaction.schema import (
    ResponseSchemaInput,
    response_schema_hash,
)
from pollux.interaction.validate import validate_interaction
from pollux.providers.base import (
    DeferredProvider,
    Provider,
    ProviderDeferredHandle,
    ProviderDeferredItem,
    ProviderDeferredSnapshot,
    ValidatingProvider,
)
from pollux.providers.models import (
    ProviderResponse,
    ToolCall,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pollux.config import Config
    from pollux.interaction.environment import Environment
    from pollux.interaction.input import Input

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


async def _validate_provider_inputs(
    provider: Provider,
    snapshot: EnvironmentSnapshot,
    inputs: Sequence[Input],
    requirements: OutputRequirements,
    config: Config,
) -> None:
    """Run provider-owned validation before deferred submission side effects."""
    if not isinstance(provider, ValidatingProvider):
        return
    # TODO: parallelize if a future provider's validate_request does I/O
    # (e.g. OpenRouter-style metadata lookups). Current validators are local.
    for inp in inputs:
        await provider.validate_request(snapshot, inp, requirements, config)


async def submit_deferred(
    environment: Environment,
    inputs: Sequence[Input],
    requirements: OutputRequirements,
    config: Config,
    provider: Provider,
) -> DeferredHandle:
    """Submit provider-backed deferred work and return the Pollux handle.

    Hands the canonical v2 primitives to the provider's deferred lifecycle,
    which compiles and submits them. Tool calling, continuation, and persistent
    caching are out of scope for deferred delivery and are not part of the
    ``defer()`` surface; capability gaps (uploads, structured outputs, reasoning)
    are rejected by :func:`validate_interaction` before submission.
    """
    # Gate on deferred support first so an unsupported provider fails with the
    # clearest message before any capability checks.
    deferred_provider = _get_deferred_provider(provider)
    inputs = tuple(inputs)
    snapshot = EnvironmentSnapshot.from_environment(
        environment, provider=config.provider
    )
    caps = resolve_capabilities(provider.capabilities, config.capabilities)
    validate_interaction(requirements, inputs, snapshot, caps, cache_requested=False)

    await _validate_provider_inputs(provider, snapshot, inputs, requirements, config)

    request_ids = _request_ids(len(inputs))
    provider_handle = await deferred_provider.submit_deferred(
        snapshot,
        list(inputs),
        requirements,
        config,
        request_ids=request_ids,
    )
    submitted_at = (
        provider_handle.submitted_at
        if provider_handle.submitted_at is not None
        else time.time()
    )
    return DeferredHandle(
        job_id=provider_handle.job_id,
        provider=config.provider,
        model=config.model,
        request_count=len(inputs),
        submitted_at=submitted_at,
        schema_hash=requirements.output_schema_hash(),
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
            hint="Omit response_schema, or re-submit with defer(response_schema=...) to enable rehydration.",
        )
    current_hash = response_schema_hash(response_schema)
    if current_hash != handle.schema_hash:
        raise ConfigurationError(
            "response_schema does not match the schema used at deferred submission time",
            hint="Pass the same schema used with defer(), or omit response_schema to collect plain dicts.",
        )


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


def _deferred_diagnostics(
    handle: DeferredHandle,
    snapshot: DeferredSnapshot,
    item: ProviderDeferredItem,
) -> dict[str, Any]:
    """Per-item deferred provenance attached to an output's diagnostics."""
    return {
        "job_id": handle.job_id,
        "request_id": item.request_id,
        "status": item.status,
        "error": item.error,
        "provider_status": item.provider_status,
        "finish_reason": item.finish_reason,
        "submitted_at": snapshot.submitted_at,
        "completed_at": snapshot.completed_at,
    }


def _output_from_item(
    item: ProviderDeferredItem,
    *,
    handle: DeferredHandle,
    snapshot: DeferredSnapshot,
    requirements: OutputRequirements,
    duration_s: float,
) -> Output:
    """Assemble one v2 ``Output`` from a collected deferred item."""
    response = _response_from_item(item)
    # A failed item carries no usable completion, so mark it as an error rather
    # than letting an empty finish reason read as a clean stop.
    error_category = None if item.status == "succeeded" else (item.error or "failed")
    output = provider_response_to_output(
        response,
        requirements=requirements,
        duration_s=duration_s,
        error_category=error_category,
    )
    raw = dict(output.diagnostics.raw or {})
    raw["deferred"] = _deferred_diagnostics(handle, snapshot, item)
    return replace(output, diagnostics=Diagnostics(raw=raw))


async def collect_deferred_handle(
    handle: DeferredHandle,
    provider: Provider,
    *,
    response_schema: ResponseSchemaInput | None = None,
) -> OutputCollection:
    """Collect a terminal deferred job into an :class:`OutputCollection`.

    Deferred work returns the same shape as ``run_many()``: one ``Output`` per
    submitted request, in submission order. Each output's
    ``diagnostics.raw["deferred"]`` carries the job id and per-item status.
    """
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

    requirements = OutputRequirements(output_schema=response_schema)
    duration_s = time.perf_counter() - start_time

    outputs: list[Output] = []
    for request_id in _request_ids(handle.request_count):
        collected_item = items_by_id.get(request_id)
        if collected_item is None:
            raise InternalError(
                f"Deferred provider did not return item {request_id!r}",
                hint="Deferred providers must return one item for every submitted request id.",
            )
        outputs.append(
            _output_from_item(
                collected_item,
                handle=handle,
                snapshot=snapshot,
                requirements=requirements,
                duration_s=duration_s,
            )
        )

    return OutputCollection(
        outputs=tuple(outputs),
        prompt_indexes=tuple(range(handle.request_count)),
    )


async def cancel_deferred_handle(handle: DeferredHandle, provider: Provider) -> None:
    """Request provider-side cancellation for a deferred job."""
    deferred_provider = _get_deferred_provider(provider)
    await deferred_provider.cancel_deferred(_provider_handle_from_handle(handle))
