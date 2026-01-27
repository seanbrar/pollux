"""Rate limiting configuration and constraints."""

from __future__ import annotations

import dataclasses

from ._validation import _require


@dataclasses.dataclass(frozen=True, slots=True)
class RateConstraint:
    """Immutable rate limit specification.

    All rates are per-minute.

    Attributes:
        requests_per_minute (int): Number of requests allowed per minute (>0).
        tokens_per_minute (int | None): Optional tokens-per-minute (>0 if provided).
        min_interval_ms (int): Minimum interval between requests in milliseconds (>=0).
        burst_factor (float): Multiplier for burst capacity (>=1.0).
    """

    requests_per_minute: int
    tokens_per_minute: int | None = None
    min_interval_ms: int = 0
    burst_factor: float = 1.0

    def __post_init__(self) -> None:
        """Validate provided values; reject invalid inputs explicitly.

        Use the centralized `_require` helpers for consistent, contextual
        validation errors (type vs value concerns separated where helpful).
        """
        # requests_per_minute: must be int and > 0
        _require(
            condition=isinstance(self.requests_per_minute, int),
            message="must be an int",
            field_name="requests_per_minute",
            exc=TypeError,
        )
        _require(
            condition=self.requests_per_minute > 0,
            message="must be > 0",
            field_name="requests_per_minute",
        )

        # tokens_per_minute: optional int > 0 when provided
        _require(
            condition=self.tokens_per_minute is None
            or isinstance(self.tokens_per_minute, int),
            message="must be an int or None",
            field_name="tokens_per_minute",
            exc=TypeError,
        )
        if self.tokens_per_minute is not None:
            _require(
                condition=self.tokens_per_minute > 0,
                message="must be > 0 when provided",
                field_name="tokens_per_minute",
            )

        # min_interval_ms: int >= 0  # noqa: ERA001
        _require(
            condition=isinstance(self.min_interval_ms, int),
            message="must be an int",
            field_name="min_interval_ms",
            exc=TypeError,
        )
        _require(
            condition=self.min_interval_ms >= 0,
            message="must be >= 0",
            field_name="min_interval_ms",
        )

        # burst_factor: numeric (int|float) and >= 1.0
        _require(
            condition=isinstance(self.burst_factor, int | float),
            message="must be numeric (int|float)",
            field_name="burst_factor",
            exc=TypeError,
        )
        _require(
            condition=self.burst_factor >= 1.0,
            message="must be >= 1.0",
            field_name="burst_factor",
        )
