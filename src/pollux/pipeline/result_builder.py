"""Result builder utilities for converting raw API responses to results.

Provides the Two-Tier Transform Chain used to produce a stable
`ResultEnvelope` from a `FinalizedCommand`: a prioritized set of
transforms (Tier 1) with a `MinimalProjection` fallback (Tier 2).

Focus: how to configure and call `ResultBuilder`, what it returns,
and when diagnostics are produced.
"""

from collections.abc import Mapping
from dataclasses import asdict
import time
from typing import Any, Never

from pollux._dev_flags import dev_validate_enabled
from pollux.core.types import (
    FinalizedCommand,
    Result,
    ResultEnvelope,
    Success,
)
from pollux.pipeline.base import BaseAsyncHandler
from pollux.pipeline.results.extraction import (
    ExtractionContext,
    ExtractionContract,
    ExtractionDiagnostics,
    ExtractionResult,
    TransformSpec,
    Violation,
)
from pollux.pipeline.results.minimal_projection import MinimalProjection
from pollux.pipeline.results.transforms import default_transforms


class ResultBuilder(BaseAsyncHandler[FinalizedCommand, ResultEnvelope, Never]):
    """Build `ResultEnvelope` objects from finalized commands.

    The `ResultBuilder` applies configured `TransformSpec`s in priority order
    and falls back to `MinimalProjection` to guarantee a deterministic,
    non-failing result. It can optionally collect extraction diagnostics.

    Attributes:
        transforms: Tuple of `TransformSpec` used by Tier 1 extraction.
        enable_diagnostics: Whether to collect `ExtractionDiagnostics`.
        allow_upstream_diagnostics: When diagnostics collection is disabled, allow
            best-effort pass-through of upstream diagnostics (e.g., model selection)
            from telemetry or locally computed advisories.
        max_text_size: Maximum response text size processed.
    """

    def __init__(
        self,
        transforms: tuple[TransformSpec, ...] | None = None,
        *,
        enable_diagnostics: bool = False,
        allow_upstream_diagnostics: bool = False,
        max_text_size: int = 1_000_000,  # 1MB limit
        validate: bool | None = None,
    ) -> None:
        """Initialize the ResultBuilder.

        Args:
            transforms: Optional sequence of `TransformSpec`. Defaults to built-ins.
            enable_diagnostics: If True, attach `ExtractionDiagnostics` to results.
            allow_upstream_diagnostics: If True and `enable_diagnostics` is False,
                pass through advisory diagnostics present in telemetry (and locally
                computed advisories) into the result envelope.
            max_text_size: Max text length to process; oversized inputs are truncated.
            validate: Enable dev-time shape validation (overrides POLLUX_PIPELINE_VALIDATE).
        """
        self.transforms = (
            transforms if transforms is not None else tuple(default_transforms())
        )
        self.enable_diagnostics = enable_diagnostics
        self._allow_upstream_diagnostics = allow_upstream_diagnostics
        self.max_text_size = max_text_size
        self._minimal_projection = MinimalProjection()
        # Pre-compute deterministic transform order (higher priority first, name tiebreaker)
        self._sorted_transforms: tuple[TransformSpec, ...] = tuple(
            sorted(self.transforms, key=lambda t: (-t.priority, t.name))
        )
        # No instance-level markers to preserve stateless contract.
        # Dev-only validation flag: correctness is guaranteed by the executor's
        # final invariant; this toggle provides stricter feedback in dev flows.
        self._validate: bool = dev_validate_enabled(override=validate)

    def _ordered_transforms(
        self, *, prefer_json_array: bool
    ) -> tuple[TransformSpec, ...]:
        """Return transforms ordered by preference and priority.

        When `prefer_json_array` is True, bubble a transform named
        "json_array" to the front while preserving priority and stable
        ordering for others.
        """
        if not prefer_json_array:
            return self._sorted_transforms
        return tuple(
            sorted(
                self.transforms,
                key=lambda t: (
                    0 if getattr(t, "name", "") == "json_array" else 1,
                    -t.priority,
                    t.name,
                ),
            )
        )

    # Note: Legacy hints-based transform ordering has been removed.

    async def handle(self, command: FinalizedCommand) -> Result[ResultEnvelope, Never]:
        """Extract a `ResultEnvelope` from a `FinalizedCommand`.

        The method applies Tier 1 transforms (priority order) and a Tier 2
        fallback (`MinimalProjection`) if none match. It performs record-only
        schema and contract validation and attaches diagnostics when enabled.

        Args:
            command: `FinalizedCommand` containing the raw API response.

        Returns:
            `Success` carrying a `ResultEnvelope` (dict). This method does not
            raise for extraction failures; validation issues are recorded.
        """
        start_time = time.perf_counter()

        raw = command.raw_api_response
        ctx = self._build_extraction_context(command)
        diagnostics = ExtractionDiagnostics() if self.enable_diagnostics else None

        # Truncate oversized responses
        if self._is_oversized(raw):
            raw = self._truncate_response(raw)
            if diagnostics:
                diagnostics.flags.add("truncated_input")

        # Tier 1: Try transforms in priority order (optionally biased by options)
        initial = command.planned.resolved.initial
        opts = getattr(initial, "options", None)
        prefer_json = bool(
            getattr(getattr(opts, "result", None), "prefer_json_array", False)
        )
        # Legacy InitialCommand.hints is deprecated and no longer considered.
        if prefer_json and diagnostics is not None:
            diagnostics.flags.add("prefer_json_array")

        extraction_result = None
        # Use ordering biased toward JSON when requested via options
        for transform in self._ordered_transforms(prefer_json_array=prefer_json):
            if diagnostics:
                diagnostics.attempted_transforms.append(transform.name)

            if transform.matcher(raw):
                try:
                    extracted_data = transform.extractor(raw, ctx.config)
                    extraction_result = self._create_extraction_result(
                        extracted_data, transform.name
                    )
                    if diagnostics:
                        diagnostics.successful_transform = transform.name
                    break
                except Exception as e:
                    if diagnostics:
                        diagnostics.transform_errors[transform.name] = str(e)
                    continue  # Try next transform

        # Tier 2: Minimal Projection fallback (always succeeds)
        if extraction_result is None:
            fallback_result = self._minimal_projection.extract(raw, ctx)
            extraction_result = fallback_result
            if diagnostics:
                diagnostics.successful_transform = fallback_result.method

        # Record pre-padding answer count for validation/diagnostics clarity
        pre_pad_count = len(extraction_result.answers)

        # Pre-compute optional model selection diagnostics (advisory)
        model_diag: dict[str, object] | None = None
        try:
            model_diag = self._compute_model_selection_diag(command)
        except Exception:
            model_diag = None

        # Build result envelope
        result_envelope = self._build_result_envelope(extraction_result, command, ctx)

        # Add hint metadata to metrics when biasing occurred
        if prefer_json:
            result_envelope.setdefault("metrics", {}).setdefault("hints", {})[
                "prefer_json_array"
            ] = True

        # Dev-only envelope shape validation
        if self._validate:
            from pollux.pipeline._devtools import validate_result_envelope

            validate_result_envelope(result_envelope, stage_name=type(self).__name__)

        # Compute total ResultBuilder stage duration
        end_time = time.perf_counter()
        builder_duration_s = end_time - start_time

        # Ensure our own stage duration is recorded alongside prior stages
        metrics = result_envelope.setdefault("metrics", {})
        durations = metrics.setdefault("durations", {})
        # Use the handler class name for consistency with executor stage names
        durations[type(self).__name__] = builder_duration_s

        # Schema validation (record-only)
        violations = self._validate_schema(result_envelope, ctx)

        # Contract validation (record-only)
        contract = ExtractionContract()
        violations.extend(contract.validate(result_envelope))

        # Add mismatch warning based on original, pre-padding/truncation count
        if pre_pad_count != ctx.expected_count:
            violations.insert(
                0,
                Violation(
                    f"Expected {ctx.expected_count} answers, got {pre_pad_count}",
                    "warning",
                ),
            )

        # Finalize diagnostics
        if diagnostics:
            diagnostics.extraction_duration_ms = builder_duration_s * 1000
            diagnostics.contract_violations = violations
            diagnostics.expected_answer_count = ctx.expected_count
            diagnostics.pre_pad_count = pre_pad_count
            # Convert to plain dict and ensure JSON-serializable fields
            diag_dict = asdict(diagnostics)
            flags = diag_dict.get("flags")
            if isinstance(flags, set):
                diag_dict["flags"] = sorted(flags)
            # Merge any upstream diagnostics (e.g., model selection) recorded in telemetry
            try:
                upstream_diag = (
                    command.telemetry_data.get("diagnostics")
                    if isinstance(command.telemetry_data, dict)
                    else None
                )
                if isinstance(upstream_diag, dict) and upstream_diag:
                    # Shallow merge under a stable envelope key
                    diag_dict.update(
                        {k: v for k, v in upstream_diag.items() if k not in diag_dict}
                    )
            except Exception:
                # Best-effort merge; ignore telemetry shape issues
                ...
            # Merge locally computed model selection diagnostics if available
            if isinstance(model_diag, dict) and model_diag:
                for k, v in model_diag.items():
                    diag_dict.setdefault(k, v)
            result_envelope["diagnostics"] = diag_dict
        elif violations:
            # Include warnings even without full diagnostics
            result_envelope["validation_warnings"] = tuple(
                v.message for v in violations
            )

        # Best-effort pass-through when diagnostics collection is disabled:
        # surface upstream diagnostics if explicitly allowed (e.g., executor wants
        # advisory diagnostics by default without full extraction diagnostics).
        if not diagnostics and self._allow_upstream_diagnostics:
            try:
                upstream_diag = (
                    command.telemetry_data.get("diagnostics")
                    if isinstance(command.telemetry_data, dict)
                    else None
                )
                if isinstance(upstream_diag, dict) and upstream_diag:
                    result_envelope["diagnostics"] = dict(upstream_diag)
            except Exception:
                # Best-effort merge; ignore telemetry shape issues
                ...
            if isinstance(model_diag, dict) and model_diag:
                # Merge or create diagnostics with local model selection diag
                d = result_envelope.setdefault("diagnostics", {})
                if isinstance(d, dict):
                    for k, v in model_diag.items():
                        d.setdefault(k, v)

        return Success(result_envelope)

    def _compute_model_selection_diag(
        self, command: FinalizedCommand
    ) -> dict[str, object] | None:
        """Compute advisory model selection diagnostics.

        Never raises; returns None on failure.
        """
        try:
            from pollux.extensions.model_selector import SelectionInputs, decide
        except Exception:
            return None

        planned = command.planned
        cfg = planned.resolved.initial.config
        model = cfg.model
        default_model = cfg.model

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
            explicit_model=True,
        )
        decision = decide(inputs)
        return {"model_selected": decision}

    def _build_extraction_context(self, command: FinalizedCommand) -> ExtractionContext:
        """Create an `ExtractionContext` from a `FinalizedCommand`.

        Args:
            command: Planned command used to derive expected answer count
                and prompts.

        Returns:
            `ExtractionContext` with `expected_count`, `prompts`, and config.
        """
        # Get expected count from prompts
        prompts = command.planned.resolved.initial.prompts
        expected_count = len(prompts) if prompts else 1

        return ExtractionContext(
            expected_count=expected_count,
            prompts=prompts,
            config={},  # TODO: Consider surfacing minimal, explicit knobs here
            # (e.g., answer cleaning rules) without leaking provider
            # concerns or introducing implicit behavior.
        )

    def _create_extraction_result(
        self, extracted_data: dict[str, Any], method: str
    ) -> ExtractionResult:
        """Normalize transform output into an `ExtractionResult`.

        Args:
            extracted_data: Raw dict returned by a transform's extractor.
            method: Name of the transform that produced the data.

        Returns:
            `ExtractionResult` with normalized `answers`, `confidence`, and
            optional `structured_data`.
        """
        return ExtractionResult(
            answers=extracted_data.get("answers", []),
            method=method,
            confidence=extracted_data.get("confidence", 0.5),
            structured_data=extracted_data.get("structured_data"),
        )

    def _build_result_envelope(
        self,
        extraction_result: ExtractionResult,
        command: FinalizedCommand,
        ctx: ExtractionContext,
    ) -> ResultEnvelope:
        """Package extraction output into a stable `ResultEnvelope` dict.

        Ensures answer count matches `ctx.expected_count`, inserts
        `structured_data` when available, and safely extracts telemetry
        metrics from `command`.

        Args:
            extraction_result: Normalized extraction result.
            command: Original command (may contain telemetry).
            ctx: Extraction context used for padding/truncation rules.

        Returns:
            `ResultEnvelope` dictionary ready for downstream consumers.
        """
        # Ensure we have the right number of answers (already normalized)
        answers = list(extraction_result.answers)
        if len(answers) < ctx.expected_count:
            # Pad with empty strings
            answers = answers + [""] * (ctx.expected_count - len(answers))
        elif len(answers) > ctx.expected_count:
            # Truncate to expected count
            answers = answers[: ctx.expected_count]

        # Build base envelope
        envelope: ResultEnvelope = {
            "status": "ok",
            "answers": answers,
            "extraction_method": extraction_result.method,
            "confidence": extraction_result.confidence,
        }

        # Add structured data if available
        if extraction_result.structured_data is not None:
            envelope["structured_data"] = extraction_result.structured_data

        # Integrate telemetry data from command with graceful degradation
        telemetry_data = (
            command.telemetry_data if isinstance(command.telemetry_data, dict) else {}
        )
        durations_obj = telemetry_data.get("durations")
        token_validation_obj = telemetry_data.get("token_validation")
        usage_obj = telemetry_data.get("usage")
        durations: dict[str, Any] = (
            dict(durations_obj) if isinstance(durations_obj, dict) else {}
        )
        token_validation: dict[str, Any] = (
            dict(token_validation_obj) if isinstance(token_validation_obj, dict) else {}
        )
        envelope["metrics"] = {
            "durations": durations,
            "token_validation": token_validation,
        }

        # Surface additional telemetry metrics (e.g., per-prompt usage, vectorization meta)
        # without overriding core fields set above.
        cmd_metrics_obj = telemetry_data.get("metrics")
        if isinstance(cmd_metrics_obj, dict) and cmd_metrics_obj:
            for k, v in cmd_metrics_obj.items():
                if k in ("durations", "token_validation"):
                    continue
                envelope["metrics"][k] = v

        # Include token usage details when provided by telemetry (optional)
        if isinstance(usage_obj, dict) and usage_obj:
            envelope["usage"] = dict(usage_obj)

        # Note: raw preview is now attached upstream (APIHandler) under
        # telemetry_data["metrics"]["raw_preview"] for pass-through.

        return envelope

    def _validate_schema(
        self, result: Mapping[str, Any], ctx: ExtractionContext
    ) -> list[Violation]:
        """Run record-only schema validation and return violations.

        This records issues for telemetry but does not raise or change the
        extraction outcome.

        Args:
            result: The `ResultEnvelope` to validate.
            ctx: Extraction context that may include a `schema`.

        Returns:
            List of `Violation` objects describing schema issues.
        """
        if ctx.schema is None:
            return []

        violations = []
        try:
            # Attempt Pydantic validation if available
            if hasattr(ctx.schema, "model_validate"):
                # Use structured_data if available, otherwise use answers
                payload = result.get("structured_data") or {
                    "answers": result["answers"]
                }
                ctx.schema.model_validate(payload)
            else:
                violations.append(
                    Violation("Schema is not a Pydantic v2 model", "info")
                )
        except Exception as e:
            violations.append(Violation(f"Schema validation failed: {e}", "warning"))

        return violations

    def _is_oversized(self, raw: Any) -> bool:
        """Return True if `raw` exceeds configured `max_text_size`.

        Args:
            raw: Raw API response to check.
        """
        if isinstance(raw, str):
            return len(raw) > self.max_text_size
        if isinstance(raw, dict):
            # Rough estimate for dict size
            return len(str(raw)) > self.max_text_size
        return False

    def _truncate_response(self, raw: Any) -> Any:
        """Truncate `raw` inputs that exceed `max_text_size`.

        The method preserves structure for dict inputs by truncating long
        string fields; for strings it truncates and appends a marker.
        """
        if isinstance(raw, str):
            if len(raw) > self.max_text_size:
                return raw[: self.max_text_size] + "... [TRUNCATED]"
            return raw
        if isinstance(raw, dict):
            # For dicts, try to truncate text fields
            truncated_dict: dict[str, Any] = {}
            for key, value in raw.items():
                if isinstance(value, str) and len(value) > self.max_text_size:
                    truncated_dict[key] = (
                        value[: self.max_text_size] + "... [TRUNCATED]"
                    )
                else:
                    truncated_dict[key] = value
            return truncated_dict
        return raw

    # Class-level marker for optional compose_pipeline validation (not required by executor)
    _produces_envelope = True
