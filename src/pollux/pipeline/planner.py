"""Execution planning stage of the pipeline.

This handler compiles an ``ExecutionPlan`` from a ``ResolvedCommand``.

Design goals (per the architecture rubric):
- Keep the planner dumb and provider-agnostic; delegate to adapters.
- Prefer small, explicit helpers over inline branching.
- Be data-centric: operate on immutable inputs and return pure artifacts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from pollux.core.exceptions import ConfigurationError
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    Failure,
    FilePlaceholder,
    HistoryPart,
    InitialCommand,
    PlannedCommand,
    PromptBundle,
    RateConstraint,
    ResolvedCommand,
    Result,
    Source,
    Success,
    TextPart,
    TokenEstimate,
    UploadTask,
)
from pollux.pipeline.base import BaseAsyncHandler
from pollux.pipeline.prompts import assemble_prompts
from pollux.pipeline.tokens.adapters.gemini import GeminiEstimationAdapter
from pollux.telemetry import TelemetryContext

if TYPE_CHECKING:
    from collections.abc import Iterable

    from pollux.config import FrozenConfig
    from pollux.core.execution_options import EstimationOptions
    from pollux.core.types import APIPart
    from pollux.telemetry import TelemetryContextProtocol

    from .tokens.adapters.base import EstimationAdapter  # pragma: no cover

log = logging.getLogger(__name__)


class ExecutionPlanner(
    BaseAsyncHandler[ResolvedCommand, PlannedCommand, ConfigurationError]
):
    """Creates execution plans from resolved commands (minimal slice).

    Responsibilities:
    - Assemble prompts (adapter: ``assemble_prompts``)
    - Estimate tokens (adapter: ``EstimationAdapter``)
    - Attach rate limits for real API runs (model limits adapter)
    """

    def __init__(
        self,
        estimation_adapter: EstimationAdapter | None = None,
        telemetry: TelemetryContextProtocol | None = None,
    ) -> None:
        """Initialize a planner with optional estimation and telemetry.

        Defaults to a Gemini-specific estimation adapter. Telemetry is optional
        and incurs zero overhead when not provided or disabled.
        """
        # Adapter is provider-neutral at this seam.
        self._adapter: EstimationAdapter
        if estimation_adapter is not None:
            self._adapter = estimation_adapter
        else:
            # Instantiate the default Gemini estimation adapter eagerly.
            self._adapter = cast("Any", GeminiEstimationAdapter)()
        # Safe no-op context when not enabled
        self._telemetry: TelemetryContextProtocol = telemetry or TelemetryContext()

    async def handle(
        self, command: ResolvedCommand
    ) -> Result[PlannedCommand, ConfigurationError]:
        """Create a minimal execution plan for the resolved command.

        This stage assembles a single `APICall` from the input prompts and
        resolved sources, computes a token estimate, and optionally attaches
        caching and rate constraints.

        Args:
            command: The resolved command (sources are already materialized).

        Returns:
            Success with `PlannedCommand` on success, otherwise a failure with
            `ConfigurationError`.
        """
        try:
            initial = command.initial
            config = initial.config
            model_name: str = self._model_name(config)

            # Options are optional and fail-soft
            overh = getattr(getattr(initial, "options", None), "estimation", None)

            # Assemble prompts using the prompt assembly system
            try:
                prompt_bundle: PromptBundle = assemble_prompts(command)
            except ConfigurationError as e:
                return Failure(e)

            # Vectorized path: when multiple user prompts are present, build
            # per-prompt calls and shared context parts.
            user_prompts = tuple(prompt_bundle.user)

            # Build shared parts (history + file placeholders) once
            shared_parts, history_turns = self._build_shared_parts(
                initial, command.resolved_sources
            )

            # If more than one prompt, switch to vectorized planning
            if len(user_prompts) > 1:
                # Build per-prompt calls. System instruction is carried in api_config
                api_cfg_base: dict[str, Any] = self._api_config(prompt_bundle.system)

                calls = tuple(
                    APICall(
                        model_name=model_name,
                        api_parts=(TextPart(text=p),),
                        api_config=dict(api_cfg_base),
                        cache_name_to_use=None,
                    )
                    for p in user_prompts
                )

                # Token estimation: compute shared (history + sources) once, then per-prompt
                history_text = self._history_to_text(history_turns)
                # Shared estimate is history-only; sources are accounted per-call
                shared_estimate = (
                    self._estimate_text_and_sources(history_text, ())
                    if history_text
                    else None
                )

                sources_agg = self._aggregate_sources(command.resolved_sources)
                per_call: list[TokenEstimate] = []
                for p in user_prompts:
                    pieces: list[TokenEstimate] = []
                    if shared_estimate is not None:
                        pieces.append(shared_estimate)
                    pieces.append(self._estimate_text_and_sources(p, ()))
                    if sources_agg is not None:
                        pieces.append(sources_agg)
                    per_call.append(
                        self._apply_estimation_override(
                            self._adapter.aggregate(pieces), overh
                        )
                    )

                total_estimate: TokenEstimate | None = (
                    self._apply_estimation_override(
                        self._adapter.aggregate(per_call), overh
                    )
                    if per_call
                    else None
                )

                # Planner remains pure: no vendor SDK/token counting here

                # Rate limits applied only for real API usage
                rate_constraint = self._resolve_rate_constraint(config, model_name)

                plan = ExecutionPlan(
                    fallback_call=None,
                    calls=calls,
                    shared_parts=tuple(shared_parts),
                    rate_constraint=rate_constraint,
                    upload_tasks=(),
                )
                planned = PlannedCommand(
                    resolved=command,
                    execution_plan=plan,
                    token_estimate=total_estimate,
                    per_call_estimates=tuple(per_call),
                )
                return Success(planned)

            # --- Single-call path ---
            joined_prompt = "\n\n".join(user_prompts)

            # Minimal prompt telemetry (keep planner lean)
            with self._telemetry("planner.prompt") as tele:
                tele.gauge("user_count", len(prompt_bundle.user))

            # Estimate tokens for prompt and resolved sources (pure, adapter-based)
            with self._telemetry("planner.estimate", model=model_name):
                estimates: list[TokenEstimate] = [
                    self._estimate_text_and_sources(joined_prompt, ())
                ]
                src_agg = self._aggregate_sources(command.resolved_sources)
                if src_agg is not None:
                    estimates.append(src_agg)
                aggregated = self._adapter.aggregate(estimates)
                aggregated = self._apply_estimation_override(aggregated, overh)
                total_estimate = self._normalize_prompt_breakdown(aggregated)

            # Planner purity: no vendor calls or SDK use here

            # Upload tasks are not planned until a richer parts mapping exists.
            # For now, the API handler infers uploads from placeholders.
            upload_tasks: tuple[UploadTask, ...] = ()

            # No cache planning. Caches are resolved during execution by CacheStage.

            # Build API parts: prompt first; file placeholders already in shared_parts
            api_parts: list[APIPart] = [TextPart(text=joined_prompt)]

            # Create API config with system instruction when present
            api_config: dict[str, Any] = self._api_config(prompt_bundle.system)

            api_call = APICall(
                model_name=model_name,
                api_parts=tuple(api_parts),
                api_config=api_config,
                cache_name_to_use=None,
            )

            # Resolve rate limits (vendor-neutral via core.models) only for real API runs.
            # In dry runs (use_real_api=False) do not attach any constraints to avoid
            # artificial delays and to keep handlers context-free. The pipeline always
            # includes the RateLimitHandler; enforcement is controlled solely by the
            # presence (or absence) of this constraint in the plan.
            rate_constraint = self._resolve_rate_constraint(config, model_name)

            plan = ExecutionPlan(
                fallback_call=None,
                calls=(api_call,),
                shared_parts=tuple(shared_parts),
                rate_constraint=rate_constraint,
                upload_tasks=upload_tasks,
            )
            planned = PlannedCommand(
                resolved=command,
                execution_plan=plan,
                token_estimate=total_estimate,
            )
            return Success(planned)
        except ConfigurationError as e:
            return Failure(e)
        except Exception as e:  # Defensive: normalize unexpected errors
            return Failure(ConfigurationError(f"Failed to plan execution: {e}"))

    # --- Internal helpers ---
    def _build_shared_parts(
        self, initial: InitialCommand, resolved_sources: tuple[Source, ...]
    ) -> tuple[list[APIPart], tuple[Any, ...]]:
        """Build shared parts (history + file placeholders) for both paths.

        Keeps handler preparation symmetrical for single and vectorized shapes.
        """
        # InitialCommand.history is validated by core types as a tuple
        # of Turn, so use it directly without redundant guards.
        history_turns = initial.history
        parts: list[APIPart] = []
        if history_turns:
            parts.append(HistoryPart(turns=history_turns))
        for s in resolved_sources:
            if s.source_type == "file":
                from pathlib import Path

                parts.append(
                    FilePlaceholder(
                        local_path=Path(str(s.identifier)), mime_type=s.mime_type
                    )
                )
            elif s.source_type == "text":
                # Add full text content to shared parts for vectorized execution
                # Use content_loader to avoid leaking only the identifier/snippet
                try:
                    raw = s.content_loader()
                except Exception:
                    raw = b""
                try:
                    text_val = raw.decode("utf-8", errors="replace")
                except Exception:
                    text_val = ""
                parts.append(TextPart(text=text_val))
            else:
                # Any non-file, non-text source with a URL-like identifier is
                # treated as a direct file reference for the provider.
                from pollux.core.types import FileRefPart

                parts.append(FileRefPart(uri=str(s.identifier), mime_type=s.mime_type))
        return parts, history_turns

    # --- Small, explicit helpers (pure) ---
    # Legacy hint extraction removed; ExecutionOptions preferred.

    def _history_to_text(self, turns: tuple[Any, ...]) -> str:
        if not turns:
            return ""
        lines: list[str] = []
        for t in turns:
            lines.append(f"User: {t.question}")
            lines.append(f"Assistant: {t.answer}")
        return "\n".join(lines)

    def _estimate_text_and_sources(
        self, text: str, sources: Iterable[Source]
    ) -> TokenEstimate:
        # Local import to avoid cycles
        from pollux.core.types import Source as _Source

        if text:
            prompt_source = _Source(
                source_type="text",
                identifier=text,
                mime_type="text/plain",
                size_bytes=len(text.encode("utf-8")),
                content_loader=lambda: text.encode("utf-8"),
            )
            estimates = [self._adapter.estimate(prompt_source)]
        else:
            estimates = []
        estimates.extend(self._adapter.estimate(s) for s in sources)
        if not estimates:
            return TokenEstimate(
                min_tokens=0,
                expected_tokens=0,
                max_tokens=0,
                confidence=1.0,
                breakdown=None,
            )
        return self._adapter.aggregate(estimates)

    def _aggregate_sources(self, sources: Iterable[Source]) -> TokenEstimate | None:
        """Aggregate token estimate for a collection of sources.

        Returns None when empty to keep call sites explicit about inclusion.
        """
        estimates = [self._adapter.estimate(s) for s in sources]
        if not estimates:
            return None
        return self._adapter.aggregate(estimates)

    def _normalize_prompt_breakdown(self, aggregated: TokenEstimate) -> TokenEstimate:
        breakdown: dict[str, TokenEstimate] | None = None
        if aggregated.breakdown:
            breakdown = {}
            for idx, (k, v) in enumerate(aggregated.breakdown.items()):
                breakdown["prompt" if idx == 0 else k] = v
        return TokenEstimate(
            min_tokens=aggregated.min_tokens,
            expected_tokens=aggregated.expected_tokens,
            max_tokens=aggregated.max_tokens,
            confidence=aggregated.confidence,
            breakdown=breakdown,
        )

    def _resolve_rate_constraint(
        self, config: FrozenConfig, model_name: str
    ) -> RateConstraint | None:
        """Resolve rate constraints from the provided FrozenConfig.

        Interacts with configuration in-kind (data-centric): consults
        `config.use_real_api` and `config.tier` directly, avoiding primitive
        threading and optional tier handling (tier is always set).
        """
        if not config.use_real_api:
            return None

        from pollux.core.models import get_rate_limits

        limits = get_rate_limits(config.tier, model_name)
        if limits is not None:
            return RateConstraint(
                requests_per_minute=limits.requests_per_minute,
                tokens_per_minute=limits.tokens_per_minute,
            )
        return None

    # (Vendor token policy helpers removed to keep planner pure)

    def _apply_estimation_override(
        self, estimate: TokenEstimate, override_hint: EstimationOptions | None
    ) -> TokenEstimate:
        """Apply conservative token estimation overrides while maintaining invariants.

        Applies widen-then-clamp logic to max_tokens and ensures expected_tokens
        remains within [min_tokens, max_tokens]. Returns original estimate if no override.
        """
        if override_hint is None:
            return estimate

        # Widen max_tokens by factor
        new_max = estimate.max_tokens
        factor = float(override_hint.widen_max_factor)
        if factor and factor != 1.0:
            new_max = int(new_max * factor)

        # Apply optional upper clamp
        if override_hint.clamp_max_tokens is not None:
            new_max = min(new_max, int(override_hint.clamp_max_tokens))

        # Ensure max >= min (invariant enforcement)
        new_max = max(new_max, estimate.min_tokens)

        # Keep expected within [min, max] bounds
        new_expected = max(estimate.min_tokens, min(estimate.expected_tokens, new_max))

        return TokenEstimate(
            min_tokens=estimate.min_tokens,
            expected_tokens=new_expected,
            max_tokens=new_max,
            confidence=estimate.confidence,
            breakdown=estimate.breakdown,
        )

    # Cache decision + identity helpers removed: now handled by CacheStage and
    # cache_identity.det_shared_key at execution time.

    def _model_name(self, config: FrozenConfig) -> str:
        return config.model

    def _api_config(self, system_instruction: str | None) -> dict[str, Any]:
        return {"system_instruction": system_instruction} if system_instruction else {}
