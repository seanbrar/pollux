"""API call planning and execution structures."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Literal

from ._validation import _freeze_mapping, _is_tuple_of, _require
from .api_parts import (
    APIPart,
    FileInlinePart,
    FilePlaceholder,
    FileRefPart,
    GenerationConfigDict,
    HistoryPart,
    TextPart,
)
from .rate_limits import RateConstraint

CacheAppliedVia = Literal["none", "plan", "override"]


@dataclasses.dataclass(frozen=True, slots=True)
class UploadTask:
    """Instruction to upload a local file and substitute an API part.

    Indexing semantics:
        part_index is relative to the per-call `APICall.api_parts` tuple.
        It does not include any shared parts. When handlers operate on a
        combined view `(shared_parts + call.api_parts)`, they must offset
        indices by `len(shared_parts)`.
    """

    part_index: int
    local_path: Path
    mime_type: str | None = None
    required: bool = True

    def __post_init__(self) -> None:
        """Validate UploadTask invariants."""
        _require(
            condition=isinstance(self.part_index, int) and self.part_index >= 0,
            message="part_index must be an int >= 0",
        )
        _require(
            condition=isinstance(self.local_path, Path),
            message="local_path must be a pathlib.Path",
            exc=TypeError,
        )
        _require(
            condition=self.mime_type is None or isinstance(self.mime_type, str),
            message="mime_type must be a str or None",
            exc=TypeError,
        )
        _require(
            condition=isinstance(self.required, bool),
            message="required must be a bool",
            exc=TypeError,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class APICall:
    """A description of a single API call to be made."""

    model_name: str
    api_parts: tuple[APIPart, ...]
    api_config: GenerationConfigDict
    # Optional best-effort cache name; adapters that support caching may reuse
    # this name. Callers must remain correct when caching is unsupported.
    cache_name_to_use: str | None = None

    def __post_init__(self) -> None:
        """Validate APICall invariants and freeze config mapping."""
        _require(
            condition=isinstance(self.model_name, str) and self.model_name != "",
            message="model_name must be a non-empty str",
            exc=TypeError,
        )
        _require(
            condition=isinstance(self.api_parts, tuple),
            message="api_parts must be a tuple",
            exc=TypeError,
        )
        valid_types = (
            TextPart,
            FileRefPart,
            FilePlaceholder,
            HistoryPart,
            FileInlinePart,
        )
        for idx, part in enumerate(self.api_parts):
            _require(
                condition=isinstance(part, valid_types),
                message=f"api_parts[{idx}] has invalid type {type(part)}; expected one of {valid_types!r}",
                exc=TypeError,
            )
        frozen = _freeze_mapping(self.api_config)
        if frozen is not None:
            object.__setattr__(self, "api_config", frozen)
        _require(
            condition=self.cache_name_to_use is None
            or isinstance(self.cache_name_to_use, str),
            message="cache_name_to_use must be a str or None",
            exc=TypeError,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Instructions for executing API calls.

    The authoritative call set is `calls`: one for sequential, many for vectorized.
    An optional `fallback_call` may be used when a primary attempt fails.
    """

    fallback_call: APICall | None = None  # For when batching fails
    # Authoritative execution set: N independent calls with shared context
    calls: tuple[APICall, ...] = ()
    shared_parts: tuple[APIPart, ...] = ()
    # Optional rate limiting constraint
    rate_constraint: RateConstraint | None = None
    # Optional pre-generation actions
    upload_tasks: tuple[UploadTask, ...] = ()
    # How a cache name (if any) was applied to this plan's calls.
    # "plan": resolved/created by CacheStage decision; "override": applied from
    # ExecutionOptions.cache_override_name; "none": no cache applied.
    cache_application: CacheAppliedVia = "none"

    def __post_init__(self) -> None:
        """Validate plan collections and optionals."""
        # Basic integrity checks on collections
        _require(
            condition=_is_tuple_of(self.calls, APICall),
            message="calls must be a tuple[APICall, ...]",
            exc=TypeError,
        )
        _require(
            condition=_is_tuple_of(
                self.shared_parts,
                (TextPart, FileRefPart, FilePlaceholder, HistoryPart, FileInlinePart),
            ),
            message="shared_parts must be a tuple[APIPart, ...]",
            exc=TypeError,
        )
        _require(
            condition=self.rate_constraint is None
            or isinstance(self.rate_constraint, RateConstraint),
            message="rate_constraint must be RateConstraint or None",
            exc=TypeError,
        )
        _require(
            condition=_is_tuple_of(self.upload_tasks, UploadTask),
            message="upload_tasks must be a tuple[UploadTask, ...]",
            exc=TypeError,
        )
        _require(
            condition=self.cache_application in {"none", "plan", "override"},
            message="cache_application must be one of {'none','plan','override'}",
        )
        _require(
            condition=len(self.calls) > 0,
            message="calls must not be empty - at least one APICall is required",
            field_name="calls",
        )
        # Coherence: if any call carries a cache name, cache_application must not be 'none'
        if self.cache_application == "none":
            has_cache_name = any(c.cache_name_to_use for c in self.calls)
            _require(
                condition=not has_cache_name,
                message=(
                    "cache_name_to_use is set on one or more calls but ExecutionPlan.cache_application is 'none'. "
                    "Use 'plan' or 'override' (prefer apply_cache_to_plan) to declare how caching was applied."
                ),
            )
        # Enforce uniformity for vectorized execution invariants
        first = self.calls[0]
        first_model = first.model_name
        first_sys = first.api_config.get("system_instruction")
        for c in self.calls[1:]:
            _require(
                condition=c.model_name == first_model,
                message="all calls must use the same model_name",
                field_name="calls",
            )
            _require(
                condition=c.api_config.get("system_instruction") == first_sys,
                message=(
                    "all calls must use the same system_instruction to ensure"
                    " stable cache identity and telemetry semantics"
                ),
                field_name="calls",
            )
        # No cache planning fields are present in ExecutionPlan.
