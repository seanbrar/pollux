"""Structured, typed execution options for the pipeline.

Prefer this over the unstructured `hints` tuple for advanced behavior.
Keeps options orthogonal and discoverable while remaining provider-neutral.
"""

from __future__ import annotations

import dataclasses
import math
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclasses.dataclass(frozen=True, slots=True)
class CacheOptions:
    """Deterministic cache identity and policy knobs.

    Consumed by the CacheStage at execution time (provider-neutral) to apply
    explicit cache names and decide reuse vs creation.

    Attributes:
        deterministic_key: Explicit cache key to use instead of computed shared key
        artifacts: Optional tuple of artifact identifiers for cache metadata
        ttl_seconds: Optional TTL override for cache entry lifetime
        reuse_only: If True, only reuse existing cache, don't create new entries
    """

    deterministic_key: str
    artifacts: tuple[str, ...] = dataclasses.field(default_factory=tuple)
    ttl_seconds: int | None = None
    reuse_only: bool = False

    def __post_init__(self) -> None:
        """Validate basic invariants for cache hints."""
        # Enforce simple, explicit invariants to reduce downstream checks
        key = (self.deterministic_key or "").strip()
        if not key:
            raise ValueError(
                "CacheOptions.deterministic_key must be a non-empty string"
            )
        if self.ttl_seconds is not None and self.ttl_seconds < 0:
            raise ValueError("CacheOptions.ttl_seconds must be >= 0 when provided")

        # Artifacts are optional metadata; if supplied, ensure all are non-empty strings
        def _all_non_empty_str(items: Iterable[str]) -> bool:
            return all(isinstance(a, str) and bool(a.strip()) for a in items)

        if self.artifacts and not _all_non_empty_str(self.artifacts):
            raise ValueError(
                "CacheOptions.artifacts must contain only non-empty strings"
            )


@dataclasses.dataclass(frozen=True, slots=True)
class EstimationOptions:
    """Hint for conservative adjustments to token estimates.

    Used by the Execution Planner to apply planner-scoped transforms to
    token estimates without introducing provider coupling. Semantics are
    conservative and explicitly bounded: the planner widens ``max_tokens``
    by ``widen_max_factor`` and then optionally clamps it to
    ``clamp_max_tokens``; invariants ``max_tokens >= min_tokens`` and
    ``expected_tokens <= max_tokens`` are enforced.

    Attributes:
        widen_max_factor: Multiply max_tokens by this factor (default 1.0 = no change)
        clamp_max_tokens: Optional upper bound to clamp max_tokens after widening
    """

    widen_max_factor: float = 1.0
    clamp_max_tokens: int | None = None

    def __post_init__(self) -> None:
        """Validate conservative override parameters."""
        # Keep override semantics conservative and explicit
        if not math.isfinite(self.widen_max_factor) or self.widen_max_factor < 1.0:
            raise ValueError(
                "EstimationOptions.widen_max_factor must be finite and >= 1.0"
            )
        if self.clamp_max_tokens is not None and self.clamp_max_tokens < 0:
            raise ValueError(
                "EstimationOptions.clamp_max_tokens must be >= 0 when provided"
            )


@dataclasses.dataclass(frozen=True, slots=True)
class ResultOption:
    """Hint for non-breaking transform preferences in extraction.

    Used by the Result Builder to bias transform order while preserving
    Tier-2 fallback guarantees. Never causes extraction to fail.

    Attributes:
        prefer_json_array: If True, bias toward json_array transform in Tier-1
    """

    prefer_json_array: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class CachePolicyHint:
    """Focused policy overrides for cache planning.

    All fields are optional; absent fields keep defaults resolved from config.
    Semantics are conservative and planner-scoped only.

    Attributes:
        first_turn_only: When True, attempt cache create only on first turn (history empty).
        respect_floor: When True, apply floor skip with confidence cut.
        conf_skip_floor: Confidence threshold [0,1] to skip when below floor.
        min_tokens_floor: Override floor in tokens; None uses model capabilities.
    """

    first_turn_only: bool | None = None
    respect_floor: bool | None = None
    conf_skip_floor: float | None = None
    min_tokens_floor: int | None = None

    def __post_init__(self) -> None:
        """Validate cache policy hint parameters after initialization."""
        if self.conf_skip_floor is not None:
            val = float(self.conf_skip_floor)
            if not (0.0 <= val <= 1.0):
                raise ValueError("conf_skip_floor must be within [0.0, 1.0]")
        if self.min_tokens_floor is not None and int(self.min_tokens_floor) < 0:
            raise ValueError("min_tokens_floor must be >= 0 when provided")


@dataclasses.dataclass(frozen=True, slots=True)
class ExecutionOptions:
    """Options to control pipeline execution behavior.

    Attributes:
        cache_policy: Policy knobs for cache creation behavior.
        cache: Deterministic cache identity and reuse/create controls.
        result: Preferences for result extraction biasing.
        estimation: Conservative overrides for token estimation.
    """

    cache_policy: CachePolicyHint | None = None
    cache: CacheOptions | None = None
    result: ResultOption | None = None
    estimation: EstimationOptions | None = None
    # Optional best-effort cache name override applied at execution time.
    # When provided, the cache stage annotates the plan's calls with this name
    # without registry lookups or creation. The terminal flow handles
    # best-effort resilience (e.g., a single no-cache retry) in a
    # provider-neutral manner.
    cache_override_name: str | None = None
    # Optional bound for client-side request fan-out within vectorized execution.
    # When None or <= 0, the handler chooses a default (sequential if constrained;
    # otherwise unbounded up to number of calls). When a rate constraint is present,
    # concurrency is forced to 1.
    request_concurrency: int | None = None
    # Optional policy to materialize remote file references (e.g., PDFs) into
    # local files before execution. Disabled by default for conservative behavior.
    remote_files: RemoteFilePolicy | None = None

    def __post_init__(self) -> None:
        """Validate simple invariants for option fields.

        - cache_override_name: when provided, must be a non-empty string after trimming.
        """
        name = self.cache_override_name
        if name is not None and (
            not isinstance(name, str) or not name.strip()
        ):  # pragma: no cover - trivial
            raise ValueError(
                "cache_override_name must be a non-empty string when provided"
            )
        rc = self.request_concurrency
        if rc is not None and int(rc) < 0:
            raise ValueError("request_concurrency must be >= 0 when provided")


def make_execution_options(
    *,
    result_prefer_json_array: bool | None = None,
    estimation: EstimationOptions | None = None,
    cache: CacheOptions | None = None,
    cache_policy: CachePolicyHint | None = None,
    cache_override_name: str | None = None,
    request_concurrency: int | None = None,
    remote_files_enabled: bool | None = None,
    remote_files: RemoteFilePolicy | None = None,
) -> ExecutionOptions:
    """Construct ExecutionOptions from slim, explicit kwargs.

    Only sets fields that are provided; keeps options orthogonal and minimal.
    """
    result = ResultOption(prefer_json_array=True) if result_prefer_json_array else None
    # Convenience: allow quick enablement without constructing a policy
    if remote_files_enabled and remote_files is None:
        remote_files = RemoteFilePolicy(enabled=True)

    return ExecutionOptions(
        cache_policy=cache_policy,
        cache=cache,
        result=result,
        estimation=estimation,
        cache_override_name=cache_override_name,
        request_concurrency=request_concurrency,
        remote_files=remote_files,
    )


@dataclasses.dataclass(frozen=True, slots=True)
class RemoteFilePolicy:
    """Policy for pre-execution remote file materialization.

    When enabled, the pipeline may download specific HTTP(S) URIs (e.g., PDFs)
    to local temporary files and express them as uploads via placeholders/tasks.

    Attributes:
        enabled: Master switch for the feature (default False).
        allowed_mime_types: MIME types eligible for materialization.
        allow_pdf_extension_heuristic: Permit extension-based detection when MIME absent.
        max_bytes: Maximum allowed bytes per download. 0 disables size enforcement.
        connect_timeout_s: Connection timeout for HTTP requests.
        read_timeout_s: Read timeout for HTTP requests.
        download_concurrency: Max concurrent downloads across the plan (>=1).
        on_error: Behavior when a download fails: 'fail' to raise an APIError, or
                  'skip' to leave the part as-is.
        allow_http: Allow plain HTTP (default False). HTTPS-only by default for safety.
        scope: Control which parts are scanned: 'shared_only' or 'shared_and_calls'.
    """

    enabled: bool = False
    allowed_mime_types: tuple[str, ...] = ("application/pdf",)
    allow_pdf_extension_heuristic: bool = True
    max_bytes: int = 25 * 1024 * 1024  # 25MB
    connect_timeout_s: float = 10.0
    read_timeout_s: float = 30.0
    download_concurrency: int = 4
    on_error: Literal["fail", "skip"] = "fail"
    allow_http: bool = False
    scope: Literal["shared_only", "shared_and_calls"] = "shared_and_calls"
