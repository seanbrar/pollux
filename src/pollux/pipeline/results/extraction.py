"""Types and small utilities for extraction result processing.

Provides the data classes and helpers used by `ResultBuilder` and transform
implementations. These types are useful for consumers implementing custom
transforms or inspecting extraction diagnostics.
"""

from __future__ import annotations

import dataclasses
import logging
import math
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

log = logging.getLogger(__name__)
# --- Transform Specification ---


@dataclasses.dataclass(frozen=True)
class TransformSpec:
    """Specification for a pure extraction transform.

    Attributes:
        name: Unique transform name.
        matcher: Callable that returns True when the transform should run.
        extractor: Callable that returns a dict with extraction output.
        priority: Higher values run before lower ones.
    """

    name: str
    matcher: Callable[[Any], bool]  # Predicate: should this transform run?
    extractor: Callable[[Any, dict[str, Any]], dict[str, Any]]  # Pure transform
    priority: int = 0  # Higher priority runs first

    def __post_init__(self) -> None:
        """Validate transform specification at construction time."""
        if not self.name or not isinstance(self.name, str):
            raise ValueError(
                f"Transform name must be non-empty string, got {self.name}"
            )

        if not callable(self.matcher):
            raise ValueError(f"Transform {self.name}: matcher must be callable")

        if not callable(self.extractor):
            raise ValueError(f"Transform {self.name}: extractor must be callable")


# --- Extraction Context ---


@dataclasses.dataclass(frozen=True)
class ExtractionContext:
    """Immutable context passed to extractors.

    Attributes:
        expected_count: Number of answers expected.
        schema: Optional Pydantic model for record-only validation.
        config: Additional transform configuration.
        prompts: Original prompts used to produce the response.
    """

    expected_count: int = 1  # Number of answers expected
    schema: Any | None = None  # Optional Pydantic schema for validation
    config: dict[str, Any] = dataclasses.field(default_factory=dict)
    prompts: tuple[str, ...] = dataclasses.field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Validate extraction context invariants."""
        if self.expected_count < 1:
            raise ValueError(f"expected_count must be >= 1, got {self.expected_count}")


# --- Contract Validation ---


@dataclasses.dataclass(frozen=True)
class Violation:
    """Record describing a contract validation issue.

    Violations are informational only and do not change extraction outcomes.
    """

    message: str
    severity: Literal["info", "warning", "error"] = "warning"

    def __post_init__(self) -> None:
        """Validate violation structure."""
        if not self.message:
            raise ValueError("Violation message cannot be empty")


@dataclasses.dataclass(frozen=True)
class ExtractionContract:
    """Contract used for record-only validation of result envelopes.

    Configure expected answer counts, length limits and required fields, and
    call `validate(result)` to obtain a list of `Violation` objects. This
    method never raises.
    """

    answer_count: int | None = None
    min_answer_length: int = 0
    max_answer_length: int = 100_000
    required_fields: frozenset[str] = dataclasses.field(default_factory=frozenset)

    def __post_init__(self) -> None:
        """Validate contract parameters."""
        if self.min_answer_length < 0:
            raise ValueError(
                f"min_answer_length must be >= 0, got {self.min_answer_length}"
            )

        if self.max_answer_length < self.min_answer_length:
            raise ValueError(
                f"max_answer_length ({self.max_answer_length}) must be >= min_answer_length ({self.min_answer_length})"
            )

    def validate(self, result: Mapping[str, Any]) -> list[Violation]:
        """Validate a `ResultEnvelope` and return violations.

        Args:
            result: The result envelope (dict) to validate.

        Returns:
            List of `Violation` records describing any contract issues.
        """
        violations: list[Violation] = []

        answers = result.get("answers", [])

        # Check expected answer count when specified
        if self.answer_count is not None:
            actual_count = len(answers)
            if actual_count != self.answer_count:
                violations.append(
                    Violation(
                        f"Expected {self.answer_count} answers, got {actual_count}",
                        "warning",
                    )
                )

        # Check answer lengths
        for i, answer in enumerate(answers):
            if not isinstance(answer, str):
                violations.append(
                    Violation(f"Answer {i} is not a string: {type(answer)}", "warning")
                )
                continue

            if len(answer) < self.min_answer_length:
                violations.append(
                    Violation(
                        f"Answer {i} length {len(answer)} < minimum {self.min_answer_length}",
                        "info",
                    )
                )

            if len(answer) > self.max_answer_length:
                violations.append(
                    Violation(
                        f"Answer {i} length {len(answer)} > maximum {self.max_answer_length}",
                        "warning",
                    )
                )

        # Check required fields
        for field in self.required_fields:
            if field not in result:
                violations.append(
                    Violation(f"Missing required field: {field}", "error")
                )

        return violations


# --- Internal Result Types ---


@dataclasses.dataclass(frozen=True)
class ExtractionResult:
    """Normalized extraction output produced by transforms.

    Attributes:
        answers: List of string answers (normalized).
        method: Name of the extraction method used.
        confidence: Confidence score in [0.0, 1.0].
        structured_data: Optional raw structured payload.
    """

    answers: list[str]
    method: str
    confidence: float
    structured_data: Any = None

    def __post_init__(self) -> None:
        """Normalize and validate extraction result invariants at the source.

        - Answers: must be a list; deep-flatten contents; bytes decode; coerce items to str.
        - Confidence: coerce to float, default on NaN/unparsable to 0.5; require [0.0, 1.0].
        - Method: must be non-empty.
        """

        # Normalize answers: deep-flatten lists/tuples; treat scalars as singletons
        def _coerce(v: Any) -> str:
            if v is None:
                return ""
            if isinstance(v, str):
                return v
            if isinstance(v, bytes | bytearray):
                try:
                    return bytes(v).decode("utf-8", errors="replace")
                except Exception:
                    return str(v)
            # Dev-only advisory when non-string scalar coerced
            nonlocal_coerce_flag[0] = True
            return str(v)

        out: list[str] = []
        # Dev-only flags
        nonlocal_coerce_flag = [False]
        nested_detected = [False]

        def _flatten(x: Any, level: int = 0) -> None:
            if isinstance(x, list | tuple):
                if level > 0:
                    nested_detected[0] = True
                for item in x:
                    _flatten(item, level + 1)
            else:
                out.append(_coerce(x))

        raw_answers = self.answers
        # Enforce list type for answers
        if not isinstance(raw_answers, list):
            raise ValueError("answers must be a list")
        _flatten(raw_answers, 0)
        object.__setattr__(self, "answers", out)

        # Dev-only advisory logs for broadened normalization
        try:
            from pollux._dev_flags import dev_validate_enabled

            if dev_validate_enabled() and (
                nested_detected[0] or nonlocal_coerce_flag[0]
            ):
                reasons: list[str] = []
                if nested_detected[0]:
                    reasons.append("nested_answer_sequence")
                if nonlocal_coerce_flag[0]:
                    reasons.append("coerced_non_string_answers")
                if reasons:
                    log.debug(
                        "ExtractionResult normalization advisory: %s",
                        ",".join(reasons),
                    )
        except Exception as e:
            log.debug("ExtractionResult advisory hook failed: %s", e)

        # Validate method
        if not self.method:
            raise ValueError("method cannot be empty")

        # Normalize and validate confidence
        raw_conf = self.confidence
        try:
            confidence = float(raw_conf)
        except Exception:
            confidence = 0.5
        else:
            if math.isnan(confidence):
                confidence = 0.5
        if not (0.0 <= confidence <= 1.0):
            raise ValueError("confidence must be in [0.0, 1.0]")
        object.__setattr__(self, "confidence", confidence)


# --- Diagnostics ---


@dataclasses.dataclass
class ExtractionDiagnostics:
    """Mutable diagnostics collected during extraction.

    Only present when a `ResultBuilder` is constructed with
    `enable_diagnostics=True`.

    Field notes:
    - `pre_pad_count` reflects the number of answers before padding/truncation
      to `expected_count` and replaces a similarly named legacy field from the
      previous system.
    """

    attempted_transforms: list[str] = dataclasses.field(default_factory=list)
    successful_transform: str | None = None
    transform_errors: dict[str, str] = dataclasses.field(default_factory=dict)
    contract_violations: list[Violation] = dataclasses.field(default_factory=list)
    flags: set[str] = dataclasses.field(default_factory=set)
    extraction_duration_ms: float | None = None
    # Optional observability fields
    expected_answer_count: int | None = None
    pre_pad_count: int | None = None


# --- Convenience Functions ---


def create_basic_context(
    expected_count: int = 1, prompts: tuple[str, ...] = (), **config_overrides: Any
) -> ExtractionContext:
    """Create a basic `ExtractionContext` with defaults.

    Args:
        expected_count: Number of answers expected.
        prompts: Optional tuple of prompts used to generate the response.
        **config_overrides: Additional config entries.

    Returns:
        `ExtractionContext` instance.
    """
    return ExtractionContext(
        expected_count=expected_count, prompts=prompts, config=dict(config_overrides)
    )
