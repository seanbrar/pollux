"""Token estimation and related data structures."""

from __future__ import annotations

import dataclasses
import typing

from ._validation import _freeze_mapping, _require


@dataclasses.dataclass(frozen=True, slots=True)
class TokenEstimate:
    """Range-based token estimate with confidence.

    Models uncertainty explicitly through ranges, allowing conservative
    or optimistic decisions based on use case needs.
    """

    min_tokens: int
    expected_tokens: int
    max_tokens: int
    confidence: float
    breakdown: typing.Mapping[str, TokenEstimate] | None = None

    def __post_init__(self) -> None:
        """Validate invariants for ordering and bounds."""
        _require(
            condition=isinstance(self.min_tokens, int) and self.min_tokens >= 0,
            message=f"must be an int >= 0, got {self.min_tokens}",
            field_name="min_tokens",
        )
        _require(
            condition=isinstance(self.expected_tokens, int)
            and self.expected_tokens >= 0,
            message=f"must be an int >= 0, got {self.expected_tokens}",
            field_name="expected_tokens",
        )
        _require(
            condition=isinstance(self.max_tokens, int) and self.max_tokens >= 0,
            message=f"must be an int >= 0, got {self.max_tokens}",
            field_name="max_tokens",
        )
        _require(
            condition=self.min_tokens <= self.expected_tokens <= self.max_tokens,
            message=f"require min <= expected <= max, got {self.min_tokens} <= {self.expected_tokens} <= {self.max_tokens}",
            field_name="token ordering",
        )
        _require(
            condition=isinstance(self.confidence, int | float)
            and 0.0 <= self.confidence <= 1.0,
            message=f"must be numeric within [0.0, 1.0], got {self.confidence}",
            field_name="confidence",
        )
        # Freeze nested breakdown map if provided
        frozen = _freeze_mapping(self.breakdown)
        if frozen is not None:
            object.__setattr__(self, "breakdown", frozen)
