"""API handling stage of the pipeline.

Implements a simple, capability-aligned execution flow with:

- Mock-by-default deterministic behavior for tests/examples
- Explicit injection for real provider adapters via constructor
- Upload substitution when supported (with optional task inference)
- Explicit cache creation/use when supported (registry-aware)
- Single fallback attempt when primary execution fails
- Orthogonal telemetry scopes for execute/generate/retry/fallback

Design focuses on data-centricity and simplicity. Remote HTTP(S) file
materialization (e.g., arXiv PDFs) occurs in the dedicated
``RemoteMaterializationStage`` prior to this handler; by the time we run,
such inputs are represented as local ``FilePlaceholder`` parts that this
handler uploads and replaces with provider file refs when supported.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
import logging
import os
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, TypedDict, cast

from pollux._dev_flags import dev_raw_preview_enabled
from pollux.core.concurrency import resolve_request_concurrency
from pollux.core.exceptions import APIError, get_http_error_hint
from pollux.core.types import (
    APICall,
    APIPart,
    ExecutionPlan,
    Failure,
    FilePlaceholder,
    FinalizedCommand,
    PlannedCommand,
    Result,
    Success,
    TextPart,
    UploadTask,
)
from pollux.pipeline._debug_preview import build_raw_preview
from pollux.pipeline.adapters.base import (
    ExecutionHintsAware,
    GenerationAdapter,
    UploadsCapability,
)
from pollux.pipeline.base import BaseAsyncHandler
from pollux.pipeline.cache_identity import det_shared_key
from pollux.pipeline.execution_state import ExecutionHints
from pollux.telemetry import TelemetryContext

if TYPE_CHECKING:
    from collections.abc import Callable

    from pollux.core.api_plan import CacheAppliedVia
    from pollux.pipeline.registries import SimpleRegistry
    from pollux.telemetry import TelemetryContextProtocol

# Note: Provider adapters are injected explicitly via `adapter` or `adapter_factory`.
# No import-time aliasing is required.

log = logging.getLogger(__name__)


class UploadPhase(str, Enum):
    """Upload processing phases with clear semantic meaning."""

    PARTITION = "partition"  # Separate registry hits from pending uploads
    UPLOAD = "upload"  # Perform concurrent uploads
    REPLACE = "replace"  # Substitute parts with uploaded references

    @classmethod
    def get_telemetry_scope(cls, phase: UploadPhase) -> str:
        """Get standardized telemetry scope name for phase."""
        return f"uploads.{phase.value}"


# --- Telemetry scopes/keys (centralized to avoid typos) ---
T_API_GENERATE = "api.generate"
T_API_RETRY_NO_CACHE = "api.retry_no_cache"
T_API_GENERATE_RETRY = "api.generate_retry"
T_API_GENERATE_RETRY_LOOP = "api.generate_retry_loop"


class TelemetryUsage(TypedDict, total=False):
    """TypedDict for telemetry usage data structure."""

    total_token_count: int


class TelemetryMetrics(TypedDict, total=False):
    """TypedDict for telemetry metrics data structure."""

    per_prompt: tuple[dict[str, Any], ...]
    vectorized_n_calls: int
    per_call_meta: tuple[dict[str, Any], ...]


class APIHandler(BaseAsyncHandler[PlannedCommand, FinalizedCommand, APIError]):
    """Executes API calls according to the execution plan.

    Defaults to a deterministic mock. A real Google SDK path is available when
    explicitly enabled via environment or configuration.
    """

    def __init__(
        self,
        telemetry: TelemetryContextProtocol | None = None,
        registries: dict[str, SimpleRegistry] | None = None,
        adapter: GenerationAdapter | None = None,
        adapter_factory: Callable[[str], GenerationAdapter] | None = None,
        *,
        include_raw_preview: bool | None = None,
    ) -> None:
        """Initialize a thin API execution handler with optional telemetry.

        registries: optional mapping with keys "cache" and "files" holding
        CacheRegistry and FileRegistry instances.
        """
        self._telemetry: TelemetryContextProtocol = telemetry or TelemetryContext()
        regs = registries or {}
        self._cache_registry = regs.get("cache")
        self._file_registry = regs.get("files")
        self._adapter: GenerationAdapter | None = adapter
        self._adapter_factory = adapter_factory
        # Debug/telemetry preview toggle (None -> inherit from env)
        self._include_raw_preview: bool | None = include_raw_preview
        # Concurrency primitives
        self._uploads_inflight: dict[str, asyncio.Future[Any]] = {}
        self._uploads_lock = asyncio.Lock()

    async def handle(
        self, command: PlannedCommand
    ) -> Result[FinalizedCommand, APIError]:
        """Handle the planned command and return a finalized command."""
        try:
            plan = command.execution_plan
            # Validate that all calls have non-empty api_parts
            for call in plan.calls:
                if not call.api_parts:
                    raise APIError("API call must have at least one part")

            adapter = self._select_adapter(command)
            # Prepare shared parts once (uploads/registries)
            effective_shared = await self._prepare_shared_parts(adapter, plan)
            finalized = await self._execute_vectorized_calls(
                adapter, command, plan, effective_shared
            )
            return Success(finalized)
        except APIError as e:
            return Failure(e)
        except Exception as e:  # Defensive normalization
            return Failure(self._wrap_api_error(f"API handler failed: {e}", e))

    def _wrap_api_error(self, message: str, error: Exception) -> APIError:
        """Wrap an exception in an APIError with an actionable hint if possible."""
        # Attempt to extract status code from common SDK/HTTP error patterns
        status_code: int | None = getattr(error, "status_code", None)
        if status_code is None:
            code = getattr(error, "code", None)
            if isinstance(code, int):
                status_code = code

        hint = get_http_error_hint(status_code) if status_code else None
        return APIError(message, hint=hint)

    # --- Internal helpers ---

    def _select_adapter(self, command: PlannedCommand) -> GenerationAdapter:
        if self._adapter is not None:
            return self._adapter
        if self._adapter_factory is not None:
            config = command.resolved.initial.config
            api_key = config.api_key
            if not api_key:
                raise APIError("Adapter factory provided but api_key missing")
            try:
                return self._adapter_factory(str(api_key))
            except Exception as e:  # pragma: no cover
                raise self._wrap_api_error(
                    f"Failed to initialize provider: {e}", e
                ) from e
        return _MockAdapter()

    # --- Cache intent modeling ---

    @dataclass(frozen=True)
    class CacheIntent:
        """Execution-time cache intent for a single call attempt."""

        applied: bool
        applied_via: CacheAppliedVia
        name: str | None

    def _derive_cache_intent(
        self,
        *,
        planned_cache_name: str | None,
        applied_via: str | None,
    ) -> APIHandler.CacheIntent:
        """Derive cache intent solely from plan annotations.

        Intent is present when a cache name exists and the plan indicates
        it was applied via either "plan" or "override".
        """
        if planned_cache_name and applied_via in {"plan", "override"}:
            via: CacheAppliedVia = "override" if applied_via == "override" else "plan"
            return APIHandler.CacheIntent(
                applied=True, applied_via=via, name=planned_cache_name
            )
        return APIHandler.CacheIntent(applied=False, applied_via="none", name=None)

    async def _prepare_effective_parts(
        self,
        adapter: GenerationAdapter | UploadsCapability,
        base_parts: list[APIPart],
        *,
        upload_tasks: tuple[UploadTask, ...] | None = None,
        infer_placeholders: bool = True,
        call_offset: int = 0,
    ) -> list[APIPart]:
        """Sanitize parts and perform upload substitution when supported.

        Callers pass explicit `upload_tasks` from the plan for per-call parts,
        or an empty tuple for shared parts. When `infer_placeholders` is True,
        FilePlaceholder entries are converted into inferred UploadTask entries.

        Explicitness note:
            If explicit `upload_tasks` are provided, they take precedence and
            no additional inference is performed unless the explicit set is
            empty. This avoids surprising partial merges; authors should include
            all desired uploads explicitly when any are specified.
        """
        effective_parts = self._sanitize_history_parts(list(base_parts))

        # Determine upload tasks: prefer explicit, else infer from placeholders
        tasks: tuple[UploadTask, ...] = upload_tasks or ()
        # UploadTask.part_index is defined relative to the per-call api_parts
        # (i.e., it does not include any shared parts). When operating on a
        # combined list of parts (shared + call), adjust indices by the length
        # of the shared prefix so replacements target the correct slots.
        if tasks and call_offset:
            from dataclasses import replace as _dc_replace

            adjusted: list[UploadTask] = []
            for t in tasks:
                adjusted.append(
                    _dc_replace(t, part_index=int(call_offset) + int(t.part_index))
                )
            tasks = tuple(adjusted)
        if not tasks and infer_placeholders:
            tasks = self._infer_upload_tasks(effective_parts)

        # If nothing to upload via placeholders and adapter lacks capability, return early
        if not tasks and not isinstance(adapter, UploadsCapability):
            return effective_parts
        if not isinstance(adapter, UploadsCapability):
            if any(t.required for t in tasks):
                raise APIError("Uploads required but not supported by provider")
            return effective_parts

        # Phase 1: registry reuse vs pending uploads
        with self._telemetry(UploadPhase.get_telemetry_scope(UploadPhase.PARTITION)):
            to_replace, pending = self._partition_uploads(tasks, effective_parts)

        # Phase 2a: perform uploads for local files (placeholder tasks)
        if pending:
            with self._telemetry(UploadPhase.get_telemetry_scope(UploadPhase.UPLOAD)):
                uploaded_results = await self._upload_pending(
                    adapter, pending, effective_parts
                )
                to_replace.extend(uploaded_results)

        # Phase 3: coerce to FileRefPart where needed and replace in parts
        with self._telemetry(UploadPhase.get_telemetry_scope(UploadPhase.REPLACE)):
            return self._replace_parts(effective_parts, to_replace)

    # ---- Focused helpers ----
    def _sanitize_history_parts(self, parts: list[APIPart]) -> list[APIPart]:
        from pollux.core.types import HistoryPart

        return [p for p in parts if not (isinstance(p, HistoryPart) and not p.turns)]

    def _infer_upload_tasks(self, parts: list[APIPart]) -> tuple[UploadTask, ...]:
        # Infer from FilePlaceholder instances in parts
        inferred: list[UploadTask] = []
        for idx, p in enumerate(parts):
            if isinstance(p, FilePlaceholder):
                inferred.append(
                    UploadTask(
                        part_index=idx,
                        local_path=p.local_path,
                        mime_type=p.mime_type,
                        required=False,
                    )
                )
        return tuple(inferred)

    def _partition_uploads(
        self, plan_uploads: tuple[UploadTask, ...], parts: list[APIPart]
    ) -> tuple[list[tuple[int, Any]], list[tuple[int, UploadTask]]]:
        to_replace: list[tuple[int, Any]] = []
        pending: list[tuple[int, UploadTask]] = []
        for task in plan_uploads:
            idx = task.part_index
            if idx >= len(parts):
                if task.required:
                    raise APIError(f"UploadTask index {idx} out of range")
                continue
            local_id = os.fspath(task.local_path)
            uploaded: Any | None = None
            if self._file_registry is not None:
                try:
                    uploaded = self._file_registry.get(local_id)
                except Exception:
                    uploaded = None
            if uploaded is not None:
                to_replace.append((idx, uploaded))
            else:
                pending.append((idx, task))
        return to_replace, pending

    async def _upload_pending(
        self,
        adapter: UploadsCapability,
        pending: list[tuple[int, UploadTask]],
        parts: list[APIPart],
    ) -> list[tuple[int, Any]]:
        async def _upload_one(i: int, t: UploadTask) -> tuple[int, Any]:
            local_id = os.fspath(t.local_path)
            # Fast path: reuse from registry when present
            if self._file_registry is not None:
                with suppress(Exception):
                    existing = self._file_registry.get(local_id)
                if existing is not None:
                    return i, existing

            # Single-flight guard: share in-flight uploads by local_id
            async with self._uploads_lock:
                fut = self._uploads_inflight.get(local_id)
                if fut is None:
                    # Use running loop for future creation (Py 3.13). This prevents
                    # implicit loop resolution quirks and is safe inside async tasks.
                    fut = asyncio.get_running_loop().create_future()
                    self._uploads_inflight[local_id] = fut
                    creator = True
                else:
                    creator = False

            if not creator:
                try:
                    uploaded = await fut
                    return i, uploaded
                finally:
                    # Creator handles cleanup
                    pass

            # We are the creator
            try:
                uploaded = await adapter.upload_file_local(t.local_path, t.mime_type)
                if self._file_registry is not None:
                    with suppress(Exception):
                        self._file_registry.set(local_id, uploaded)
                fut.set_result(uploaded)
                # Best-effort cleanup: unlink ephemeral placeholders after upload
                try:
                    if 0 <= i < len(parts):
                        ph = parts[i]
                        if isinstance(ph, FilePlaceholder) and getattr(
                            ph, "ephemeral", False
                        ):
                            with suppress(Exception):
                                Path(os.fspath(t.local_path)).unlink()
                except Exception as _cleanup_err:
                    # Never fail upload due to cleanup; surface at debug level
                    log.debug("Ephemeral file cleanup failed: %s", _cleanup_err)
                return i, uploaded
            except Exception as e:
                fut.set_exception(e)
                raise
            finally:
                async with self._uploads_lock:
                    self._uploads_inflight.pop(local_id, None)

        return await asyncio.gather(*(_upload_one(i, t) for i, t in pending))

    def _coerce_to_file_ref(self, uploaded: Any) -> Any:
        from pollux.core.types import FileRefPart

        if isinstance(uploaded, FileRefPart):
            return uploaded
        # Try attribute-based coercion
        try:
            uri_attr = cast("Any", uploaded).uri
            if isinstance(uri_attr, str):
                return FileRefPart(
                    uri=uri_attr,
                    mime_type=getattr(uploaded, "mime_type", None),
                    raw_provider_data=uploaded,
                )
        except AttributeError:
            pass
        # Try mapping-based coercion
        if (
            isinstance(uploaded, dict)
            and "uri" in uploaded
            and isinstance(uploaded.get("uri"), str)
        ):
            return FileRefPart(
                uri=uploaded["uri"],
                mime_type=cast("Any", uploaded).get("mime_type"),
                raw_provider_data=uploaded,
            )
        return uploaded

    def _replace_parts(
        self, parts: list[APIPart], replacements: list[tuple[int, Any]]
    ) -> list[APIPart]:
        effective = list(parts)
        for idx, uploaded in replacements:
            effective[idx] = self._coerce_to_file_ref(uploaded)
        return effective

    async def _prepare_shared_parts(
        self, adapter: GenerationAdapter, plan: ExecutionPlan
    ) -> list[APIPart]:
        """Prepare effective shared parts once (uploads/registries).

        UploadTasks are not applied to shared parts (indices are per-call), but
        placeholder inference is allowed.
        """
        shared = list(plan.shared_parts)
        return await self._prepare_effective_parts(
            adapter,
            shared,
            upload_tasks=(),
            infer_placeholders=True,
        )

    def _combine_shared_with_call(
        self, shared: list[APIPart], call_parts: tuple[APIPart, ...]
    ) -> tuple[APIPart, ...]:
        """Combine effective shared parts with per-call parts for execution."""
        return tuple(shared) + tuple(call_parts)

    async def _execute_single_call(
        self, adapter: GenerationAdapter, command: PlannedCommand, plan: ExecutionPlan
    ) -> FinalizedCommand:
        """Deprecated path; single-call executes through vectorized machinery."""
        shared = await self._prepare_shared_parts(adapter, plan)
        return await self._execute_vectorized_calls(adapter, command, plan, shared)

    async def _execute_vectorized_calls(
        self,
        adapter: GenerationAdapter,
        command: PlannedCommand,
        plan: ExecutionPlan,
        effective_shared: list[APIPart],
    ) -> FinalizedCommand:
        """Execute vectorized calls with shared context and aggregate telemetry.

        Supports optional bounded fan-out when no rate constraint is present.
        """
        n = len(plan.calls)
        raw_list: list[dict[str, Any]] = [{} for _ in range(n)]
        per_prompt_usage: list[dict[str, Any]] = [{} for _ in range(n)]
        per_call_meta: list[dict[str, Any]] = [{} for _ in range(n)]

        # Determine allowed concurrency using shared resolver
        options = getattr(command.resolved.initial, "options", None)
        cfg = command.resolved.initial.config
        has_constraint = command.execution_plan.rate_constraint is not None
        concurrency = resolve_request_concurrency(
            n_calls=n,
            options=options,
            cfg=cfg,
            rate_constrained=has_constraint,
        )
        sem = asyncio.Semaphore(concurrency)

        async def _one(i: int) -> None:
            call = plan.calls[i]
            combined_parts = self._combine_shared_with_call(
                effective_shared, call.api_parts
            )
            # Prepare effective parts per-call as well to ensure any placeholders
            # in per-call parts are uploaded and replaced consistently.
            # Prepare again at per-call granularity. Shared parts were already
            # sanitized and had placeholders resolved; this pass handles any
            # per-call placeholders uniformly and is a no-op for effective shared parts.
            prepared_parts = await self._prepare_effective_parts(
                adapter,
                list(combined_parts),
                upload_tasks=plan.upload_tasks,
                infer_placeholders=True,
                call_offset=len(effective_shared),
            )
            async with sem:
                t0 = perf_counter()
                if isinstance(adapter, _MockAdapter):
                    ptxt = self._extract_text_from_parts(tuple(prepared_parts))
                    raw = {
                        "mock": True,
                        "model": call.model_name,
                        "text": f"echo: {ptxt}",
                        "usage": {
                            "prompt_token_count": max(len(ptxt) // 4 + 10, 0),
                            "source_token_count": 0,
                            "total_token_count": max(len(ptxt) // 4 + 10, 0),
                        },
                    }
                    used_fallback = False
                    retried_without_cache = False
                    primary_error_repr = None
                    api_time_s = 0.0
                else:
                    (
                        raw,
                        used_fallback,
                        retried_without_cache,
                        primary_error_repr,
                        api_time_s,
                    ) = await self._execute_with_resilience(
                        adapter,
                        command,
                        call,
                        tuple(prepared_parts),
                        call.cache_name_to_use,
                    )
                raw_list[i] = raw
                per_prompt_usage[i] = dict(cast("dict[str, Any]", raw.get("usage", {})))
                meta: dict[str, Any] = {}
                if used_fallback:
                    meta["used_fallback"] = True
                if retried_without_cache:
                    meta["retried_without_cache"] = True
                if primary_error_repr:
                    meta["primary_error"] = primary_error_repr
                # Attach per-call duration (execution time within semaphore)
                total_dur = max(perf_counter() - t0, 0.0)
                meta["duration_s"] = total_dur
                # Provide a split between provider API time and non-API time
                try:
                    api_dur = float(api_time_s)
                except Exception:
                    api_dur = 0.0
                api_dur = api_dur if api_dur >= 0.0 else 0.0
                meta["api_time_s"] = api_dur
                meta["non_api_time_s"] = max(total_dur - api_dur, 0.0)

                # Indicate whether a cache was applied to this call via the plan
                meta["cache_applied"] = bool(call.cache_name_to_use)
                per_call_meta[i] = meta

        await asyncio.gather(*(_one(i) for i in range(n)))

        # Build finalized result with aggregated usage in telemetry
        finalized = FinalizedCommand(
            planned=command,
            raw_api_response={
                "model": plan.calls[0].model_name,
                "batch": tuple(raw_list),
            },
        )

        # Attach usage and per-prompt metrics prior to validation
        self._attach_vectorized_usage(
            finalized,
            per_prompt_usage=per_prompt_usage,
            n_calls=len(plan.calls),
            per_call_meta=per_call_meta,
        )

        # Surface execution-level metrics helpful for batch efficiency analysis
        try:
            metrics = cast(
                "dict[str, Any]", finalized.telemetry_data.setdefault("metrics", {})
            )
            metrics["concurrency_used"] = concurrency
            metrics["cache_application"] = plan.cache_application
            # Aggregate simple per-call flags for dashboards (high-value, low coupling)
            try:
                pcm = metrics.get("per_call_meta")
                if isinstance(pcm, list | tuple):
                    metrics["retry_no_cache_count"] = sum(
                        1
                        for m in pcm
                        if isinstance(m, dict) and m.get("retried_without_cache")
                    )
                    metrics["fallback_count"] = sum(
                        1 for m in pcm if isinstance(m, dict) and m.get("used_fallback")
                    )

                    # Aggregate total API and non-API time across calls (best-effort)
                    def _num(x: Any) -> float:
                        try:
                            return float(x)
                        except Exception:
                            return 0.0

                    metrics["api_time_total_s"] = sum(
                        _num(cast("dict[str, Any]", m).get("api_time_s"))
                        for m in pcm
                        if isinstance(m, dict)
                    )
                    metrics["non_api_time_total_s"] = sum(
                        _num(cast("dict[str, Any]", m).get("non_api_time_s"))
                        for m in pcm
                        if isinstance(m, dict)
                    )
            except Exception as _agg_err:
                # Best-effort; keep envelope robust if shape varies
                log.debug(
                    "Failed to aggregate per-call flags; continuing.",
                    exc_info=_agg_err,
                )
            # Surface per-call estimates when available for prediction vs actual analysis
            if command.per_call_estimates:
                metrics["per_call_estimates"] = tuple(
                    {
                        "min_tokens": e.min_tokens,
                        "expected_tokens": e.expected_tokens,
                        "max_tokens": e.max_tokens,
                        "confidence": e.confidence,
                    }
                    for e in command.per_call_estimates
                )
        except Exception as e:
            # Best-effort: never fail execution due to metrics attachment
            log.debug("Failed to attach execution metrics; continuing.", exc_info=e)

        # Token validation compares estimated aggregate to actual aggregate
        self._attach_token_validation(finalized)

        # Attach auto model selection diagnostics (best-effort, advisory)
        try:
            self._attach_model_selection_diag(finalized)
        except Exception as _diag_err:
            log.debug(
                "Model selection diagnostics attach failed; continuing.",
                exc_info=_diag_err,
            )

        # Optionally attach compact raw previews for researcher debugging
        try:
            enabled = (
                self._include_raw_preview
                if self._include_raw_preview is not None
                else dev_raw_preview_enabled()
            )
            if enabled:
                previews = tuple(build_raw_preview(r) for r in raw_list)
                dbg = cast(
                    "dict[str, Any]", finalized.telemetry_data.setdefault("metrics", {})
                )
                # Keep under metrics for envelope pass-through without schema changes
                dbg["raw_preview"] = {  # compact, provider-agnostic view
                    "model": plan.calls[0].model_name,
                    "batch": previews,
                }
        except Exception as e:
            log.debug("Failed to attach raw_preview; continuing.", exc_info=e)
        return finalized

    def _extract_text_from_parts(self, parts: tuple[APIPart, ...]) -> str:
        """Return the last text from parts when present, else empty string.

        This mirrors the behavior used for mock vectorized responses and avoids
        leaking provider-specific shapes.
        """
        for part in reversed(parts):
            if isinstance(part, TextPart):
                return part.text
        return ""

    def _attach_vectorized_usage(
        self,
        finalized: FinalizedCommand,
        *,
        per_prompt_usage: list[dict[str, Any]],
        n_calls: int,
        per_call_meta: list[dict[str, Any]],
    ) -> None:
        """Aggregate and attach vectorized usage and metrics to telemetry."""
        total_tokens = self._sum_usage_total_tokens(per_prompt_usage)
        usage = cast("TelemetryUsage", finalized.telemetry_data.setdefault("usage", {}))
        usage["total_token_count"] = total_tokens
        metrics = cast(
            "TelemetryMetrics", finalized.telemetry_data.setdefault("metrics", {})
        )
        metrics["per_prompt"] = tuple(per_prompt_usage)
        metrics["vectorized_n_calls"] = n_calls
        metrics["per_call_meta"] = tuple(per_call_meta)

    def _sum_usage_total_tokens(self, usage_list: list[dict[str, Any]]) -> int:
        total = 0
        for u in usage_list:
            try:
                total += int(u.get("total_token_count", 0) or 0)
            except Exception:
                total += 0
        return total

    def _attach_model_selection_diag(self, finalized: FinalizedCommand) -> None:
        """Compute and attach model selection decision for diagnostics.

        This is advisory only; it never changes the planned model.
        """
        try:
            from pollux.extensions.model_selector import SelectionInputs, decide
        except Exception:
            return

        planned = finalized.planned
        cfg = planned.resolved.initial.config
        model = cfg.model
        default_model = cfg.model  # fallback default (no separate default in cfg)

        # Prefer aggregate estimate when available; else sum per-call
        total_est = 0
        if planned.token_estimate is not None:
            total_est = int(getattr(planned.token_estimate, "expected_tokens", 0) or 0)
        elif planned.per_call_estimates:
            total_est = sum(
                int(getattr(e, "expected_tokens", 0) or 0)
                for e in planned.per_call_estimates
            )

        prompt_count = max(1, len(planned.execution_plan.calls))
        caching_enabled = bool(cfg.enable_caching)

        # Heavy multimodal heuristic: any non-text source or media mime-types
        heavy_mm = False
        for s in planned.resolved.resolved_sources:
            try:
                mt = (s.mime_type or "").lower()
            except Exception:
                mt = ""
            if s.source_type != "text" or mt.startswith(("video/", "audio/", "image/")):
                heavy_mm = True
                break

        inputs = SelectionInputs(
            total_est_tokens=total_est,
            prompt_count=prompt_count,
            caching_enabled=caching_enabled,
            heavy_multimodal=heavy_mm,
            configured_default=default_model,
            configured_model=model,
            # With no provenance inside FinalizedCommand, conservatively assume explicit
            explicit_model=True,
        )
        decision = decide(inputs)
        diag = finalized.telemetry_data.setdefault("diagnostics", {})
        if isinstance(diag, dict):
            diag["model_selected"] = decision

    # Cache resolution is handled by CacheStage; no planning-time cache logic here

    async def _execute_with_resilience(
        self,
        adapter: GenerationAdapter,
        command: PlannedCommand,
        primary: APICall,
        parts: tuple[APIPart, ...],
        cache_name: str | None,
    ) -> tuple[dict[str, Any], bool, bool, str | None, float]:
        used_fallback = False
        retried_without_cache = False
        primary_error_repr: str | None = None
        total_api_time_s: float = 0.0
        with self._telemetry("api.execute", model=primary.model_name):
            try:
                # Convert Mapping to dict for the method that needs to modify it
                api_config_dict: dict[str, object] = dict(primary.api_config)
                (
                    raw_response,
                    retried_without_cache,
                    api_time_s,
                ) = await self._generate_with_resilience(
                    adapter,
                    primary.model_name,
                    parts,
                    api_config_dict,
                    cache_name,
                    planned_command=command,
                )
                total_api_time_s += float(api_time_s or 0.0)
            except Exception as primary_error:
                if command.execution_plan.fallback_call is None:
                    raise self._wrap_api_error(
                        f"Provider call failed: {primary_error}", primary_error
                    ) from primary_error
                try:
                    fb = command.execution_plan.fallback_call
                    if fb is None:
                        raise APIError("Fallback plan unexpectedly missing")
                    with self._telemetry("api.fallback", model=fb.model_name):
                        used_fallback = True
                        primary_error_repr = str(primary_error)
                        if isinstance(adapter, _MockAdapter):
                            raw_response = self._build_mock_response(
                                self._rebuild_for_fallback(command)
                            )
                            api_time = 0.0
                        else:
                            # Reuse centralized no-cache generation helper for timing and hints
                            raw_response, api_time = await self._retry_without_cache(
                                adapter,
                                fb.model_name,
                                tuple(fb.api_parts),
                                dict(fb.api_config),
                            )
                        total_api_time_s += api_time
                    # Fallback path does not imply primary no-cache retry
                    retried_without_cache = False
                except Exception as fallback_error:
                    raise self._wrap_api_error(
                        f"Fallback failed after primary error: {primary_error}; fallback error: {fallback_error}",
                        fallback_error,
                    ) from fallback_error
        return (
            raw_response,
            used_fallback,
            retried_without_cache,
            primary_error_repr,
            total_api_time_s,
        )

    def _build_mock_response(self, command: PlannedCommand) -> dict[str, Any]:
        call0 = command.execution_plan.calls[0]
        return self._build_mock_response_from_parts(tuple(call0.api_parts), command)

    def _build_mock_response_from_parts(
        self, parts: tuple[APIPart, ...], command: PlannedCommand
    ) -> dict[str, Any]:
        first_text = ""
        if parts:
            p0 = parts[0]
            first_text = cast("Any", p0).text if hasattr(p0, "text") else str(p0)
        estimate = command.token_estimate
        if estimate is not None:
            prompt_tokens = max(len(first_text) // 4 + 10, 0)
            source_tokens = max(estimate.expected_tokens - prompt_tokens, 0)
            total_tokens = prompt_tokens + source_tokens
        else:
            prompt_tokens = len(first_text) // 4 + 10
            source_tokens = 0
            total_tokens = prompt_tokens

        return {
            "mock": True,
            "model": command.execution_plan.calls[0].model_name,
            "text": f"echo: {first_text}",
            "usage": {
                "prompt_token_count": prompt_tokens,
                "source_token_count": source_tokens,
                "total_token_count": total_tokens,
            },
        }

    def _rebuild_for_fallback(self, command: PlannedCommand) -> PlannedCommand:
        """Return a PlannedCommand whose `calls` contain the fallback APICall.

        Preserves immutability and carries over shared parts, rate constraints,
        and upload tasks to maintain execution semantics in the fallback path.
        """
        plan = command.execution_plan
        if plan.fallback_call is None:
            return command
        from pollux.core.types import ExecutionPlan as _Plan  # local import

        new_plan = _Plan(
            calls=(plan.fallback_call,),
            fallback_call=None,
            shared_parts=plan.shared_parts,
            rate_constraint=plan.rate_constraint,
            upload_tasks=plan.upload_tasks,
        )
        return PlannedCommand(
            resolved=command.resolved,
            execution_plan=new_plan,
            token_estimate=command.token_estimate,
        )

    def _attach_token_validation(self, finalized: FinalizedCommand) -> None:
        # FinalizedCommand guarantees telemetry_data is a dict, TokenEstimate validates its invariants
        estimate = finalized.planned.token_estimate
        if not estimate:
            return
        usage: dict[str, Any] = {}
        try:
            raw = finalized.raw_api_response
            if isinstance(raw, dict):
                usage = cast("dict[str, Any]", raw.get("usage", {}))
        except Exception:
            usage = {}
        actual = (
            int(usage.get("total_token_count", 0)) if isinstance(usage, dict) else 0
        )
        # Vectorized path: fall back to telemetry usage totals when raw lacks usage
        if actual == 0:
            try:
                tele_usage = finalized.telemetry_data.get("usage", {})
                if isinstance(tele_usage, dict):
                    actual = int(tele_usage.get("total_token_count", 0) or 0)
            except Exception:
                actual = 0
        cast(
            "dict[str, object]",
            finalized.telemetry_data.setdefault("token_validation", {}),
        ).update(
            {
                "estimated_expected": estimate.expected_tokens,
                "estimated_min": estimate.min_tokens,
                "estimated_max": estimate.max_tokens,
                "actual": actual,
                "in_range": estimate.min_tokens <= actual <= estimate.max_tokens,
            }
        )

    def _attach_usage_data(self, finalized: FinalizedCommand) -> None:
        """Extract usage data from API response and attach to telemetry."""
        if not isinstance(finalized.telemetry_data, dict):
            return
        usage: dict[str, Any] = {}
        try:
            raw = finalized.raw_api_response
            if isinstance(raw, dict):
                usage = cast("dict[str, Any]", raw.get("usage", {}))
        except Exception:
            usage = {}

        if usage:
            finalized.telemetry_data["usage"] = dict(usage)

    def _with_cache(
        self, api_config: dict[str, object], cache_name: str | None
    ) -> dict[str, object]:
        if not cache_name:
            return dict(api_config)
        cfg = dict(api_config)
        # Provider-specific adapters may interpret this key; harmless for mock
        cfg.setdefault("cached_content", cache_name)
        return cfg

    # --- Resilience helpers ---

    def _apply_adapter_hints(
        self, adapter: GenerationAdapter, cached_content: str | None
    ) -> None:
        """Apply execution hints to adapter when supported (best-effort)."""
        if isinstance(adapter, ExecutionHintsAware):
            with suppress(Exception):
                adapter.apply_hints(ExecutionHints(cached_content=cached_content))

    async def _attempt_generate(
        self,
        adapter: GenerationAdapter,
        model_name: str,
        parts: tuple[APIPart, ...],
        api_config: dict[str, object],
        cache_name: str | None,
    ) -> tuple[dict[str, Any], float]:
        """Single generation attempt with optional cache application."""
        self._apply_adapter_hints(adapter, cache_name)
        _t0 = perf_counter()
        raw = await adapter.generate(
            model_name=model_name,
            api_parts=parts,
            api_config=self._with_cache(api_config, cache_name),
        )
        return raw, max(perf_counter() - _t0, 0.0)

    async def _retry_without_cache(
        self,
        adapter: GenerationAdapter,
        model_name: str,
        parts: tuple[APIPart, ...],
        api_config: dict[str, object],
    ) -> tuple[dict[str, Any], float]:
        """One retry without cache, marking telemetry flag for caller."""
        self._apply_adapter_hints(adapter, None)
        _t0 = perf_counter()
        raw = await adapter.generate(
            model_name=model_name,
            api_parts=parts,
            api_config=dict(api_config),
        )
        return raw, max(perf_counter() - _t0, 0.0)

    async def _backoff_generate(
        self,
        adapter: GenerationAdapter,
        model_name: str,
        parts: tuple[APIPart, ...],
        api_config: dict[str, object],
        *,
        attempts: int = 2,
        base_delay: float = 0.5,
        initial_error: Exception,
    ) -> tuple[dict[str, Any], float]:
        """Small backoff loop for transient errors; raises last error if exhausted."""
        # If the initial error is not transient, don't retry pointlessly
        if not self._is_transient_error(initial_error):
            raise initial_error

        last_error: Exception = initial_error
        for i in range(attempts):
            from random import random

            sleep_for = base_delay * (2**i) * (1 + 0.25 * random())  # noqa: S311
            await asyncio.sleep(sleep_for)
            try:
                with self._telemetry(
                    T_API_GENERATE_RETRY, model=model_name, attempt=i + 1
                ):
                    _t0 = perf_counter()
                    raw = await adapter.generate(
                        model_name=model_name,
                        api_parts=parts,
                        api_config=dict(api_config),
                    )
                    return raw, max(perf_counter() - _t0, 0.0)
            except Exception as e:  # keep last error
                # If the new error is not transient, raise immediately
                if not self._is_transient_error(e):
                    raise e
                last_error = e
                # Note: we only count API time on successful attempt; failed attempts are
                # not observable via envelope metrics and would bias totals across failures.
        # Exhausted retries; raise the last transient error
        raise last_error

    async def _generate_with_resilience(
        self,
        adapter: GenerationAdapter,
        model_name: str,
        parts: tuple[APIPart, ...],
        api_config: dict[str, object],
        cache_name: str | None,
        planned_command: PlannedCommand,
    ) -> tuple[dict[str, Any], bool, float]:
        """Generate with cache hinting and minimal retry logic.

        Behavior:
        - If adapter is the mock, execute once deterministically (no retries).
        - If a cache name is present (from plan or exec-time hint), apply it
          and attempt generation.
        - On error and when caching was intended (explicit plan or exec-time
          override), retry once without cache and mark the retry in telemetry.
        - For recognized transient errors, perform a small backoff loop (2 tries).
        """
        retried_without_cache = False
        api_time_accum = 0.0

        # Mock path remains deterministic and never retries
        if isinstance(adapter, _MockAdapter):
            with self._telemetry(T_API_GENERATE, model=model_name):
                return (
                    self._build_mock_response_from_parts(parts, planned_command),
                    retried_without_cache,
                    0.0,
                )

        # Derive intent from plan (includes override vs plan origin when available)
        intent = self._derive_cache_intent(
            planned_cache_name=cache_name,
            applied_via=getattr(
                planned_command.execution_plan, "cache_application", "none"
            ),
        )
        # Override path is expressed via plan.cache_application

        # Real path: attempt with cache hint first (if provided)
        last_error: Exception | None = None
        try:
            with self._telemetry(T_API_GENERATE, model=model_name) as tele:
                # Lightweight, explicit gauges for clarity
                tele.gauge(
                    "cache_intent_plan", 1 if intent.applied_via == "plan" else 0
                )
                tele.gauge(
                    "cache_intent_override",
                    1 if intent.applied_via == "override" else 0,
                )
                tele.gauge("cache_applied", 1 if intent.applied else 0)
                # If cache is applied, write metadata to registry (best-effort)
                if intent.applied and intent.name:
                    self._write_cache_metadata(
                        planned_command,
                        intent.name,
                        applied_via=intent.applied_via,
                    )
                raw, api_t = await self._attempt_generate(
                    adapter, model_name, parts, api_config, cache_name
                )
                api_time_accum += api_t
                return raw, retried_without_cache, api_time_accum
        except Exception as first_error:
            # Retry without cache only if caching was truly intended and applied
            if intent.applied and intent.applied_via in {"plan", "override"}:
                with self._telemetry(T_API_RETRY_NO_CACHE, model=model_name):
                    try:
                        raw, api_t = await self._retry_without_cache(
                            adapter, model_name, parts, api_config
                        )
                        retried_without_cache = True
                        api_time_accum += api_t
                        return raw, retried_without_cache, api_time_accum
                    except Exception:
                        # fall through to backoff retries on transient errors
                        last_error = first_error
            else:
                last_error = first_error

        # Backoff transient errors (raises when exhausted)
        with self._telemetry(T_API_GENERATE_RETRY_LOOP, model=model_name):
            # Defensive: ensure non-None for typing without using assert.
            initial_err: Exception = (
                last_error
                if last_error is not None
                else Exception("initial error missing")
            )
            raw, api_t = await self._backoff_generate(
                adapter,
                model_name,
                parts,
                api_config,
                attempts=2,
                base_delay=0.5,
                initial_error=initial_err,
            )
            api_time_accum += api_t
            return raw, retried_without_cache, api_time_accum

    def _is_transient_error(self, err: Exception) -> bool:
        text = str(err).lower()
        return (
            "timeout" in text
            or "timed out" in text
            or "429" in text
            or "rate limit" in text
            or "temporarily" in text
            or "unavailable" in text
        )

    # --- Cache metadata helpers ---
    def _write_cache_metadata(
        self, planned_command: PlannedCommand, cache_name: str, *, applied_via: str
    ) -> None:
        """Best-effort write of cache metadata to the cache registry.

        Stores the applied cache name and any artifacts from CacheOptions under the
        deterministic shared-context key used by CacheStage. Unknown registry
        types are ignored safely.
        """
        reg = self._cache_registry
        if reg is None:
            return
        try:
            initial = planned_command.resolved.initial
            opts = getattr(initial, "options", None)
            cache_hint = getattr(opts, "cache", None) if opts is not None else None

            plan = planned_command.execution_plan
            model_name = plan.calls[0].model_name
            sys_instr = plan.calls[0].api_config.get("system_instruction")
            sys_text = str(sys_instr) if sys_instr is not None else None

            key = det_shared_key(model_name, sys_text, planned_command)
            setter = getattr(reg, "set_meta", None)
            if callable(setter):
                setter(
                    key,
                    {
                        "cache_name": cache_name,
                        "artifacts": tuple(cache_hint.artifacts) if cache_hint else (),
                        "applied_via": applied_via
                        if applied_via in {"plan", "override"}
                        else "none",
                    },
                )
        except Exception:
            # Best-effort: never fail execution due to metadata
            return


class _MockAdapter(GenerationAdapter):
    """Deterministic adapter used for tests/examples (no network)."""

    async def upload_file_local(
        self, path: os.PathLike[str] | str, mime_type: str | None
    ) -> Any:
        # Return a neutral FileRefPart-like mapping with a fake URI
        from pollux.core.types import FileRefPart

        return FileRefPart(
            uri=f"mock://uploaded/{os.fspath(path)}", mime_type=mime_type
        )

    async def create_cache(
        self,
        *,
        model_name: str,
        content_parts: tuple[Any, ...],
        system_instruction: str | None,
        ttl_seconds: int | None,  # noqa: ARG002
    ) -> str:
        # Deterministic pseudo cache name for testing; model-bound
        base = (system_instruction or "") + "|".join(
            str(getattr(p, "uri", getattr(p, "text", p))) for p in content_parts
        )
        suffix = hex(abs(hash((model_name, base))) % (1 << 32))[2:]
        return f"cachedContents/mock-{model_name}-{suffix}"

    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],
        api_config: dict[str, object],  # noqa: ARG002
    ) -> dict[str, Any]:
        # The handler builds the final mock response to incorporate token estimate logic.
        # This adapter simply echoes the first text part to keep behavior explicit.
        first_text = ""
        try:
            part0 = next(iter(api_parts))
            if hasattr(part0, "text"):
                first_text = cast("Any", part0).text
            elif isinstance(part0, dict) and "text" in part0:
                first_text = str(part0["text"])  # pragma: no cover
            else:
                first_text = str(part0)
        except StopIteration:
            first_text = ""
        return {"model": model_name, "text": f"echo: {first_text}"}


## Note: Real provider adapter implementation lives in
## `pollux.pipeline.adapters.gemini.GoogleGenAIAdapter` and should be
## passed explicitly via `APIHandler(adapter=...)` or `adapter_factory=...`.
