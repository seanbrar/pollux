"""Rate limiting middleware for the Command Pipeline.

Implements a vendor-neutral handler that enforces per-plan RateConstraint
before API execution. Uses minimal micro-limiters and emits telemetry.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import time

# Removed ConfigCompatibilityShim import - no longer needed
from pollux.core.exceptions import GeminiBatchError
from pollux.core.types import PlannedCommand, RateConstraint, Result, Success
from pollux.pipeline.base import BaseAsyncHandler
from pollux.telemetry import TelemetryContext, TelemetryContextProtocol


class RateLimitMiddlewareError(GeminiBatchError):
    """Placeholder error type; handler is not expected to fail."""


@dataclass
class MicroLimiter:
    """Minimal limiter using a monotonic clock.

    Separate instances can be composed to form dual limiters.
    """

    clock: Callable[[], float] = time.monotonic
    _last_time: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire_request(self, requests_per_minute: int) -> float:
        """Acquire a single request permit and return the wait time applied."""
        if requests_per_minute <= 0:
            return 0.0
        min_interval = 60.0 / float(requests_per_minute)
        async with self._lock:
            now = self.clock()
            elapsed = now - self._last_time
            wait_time = 0.0
            if elapsed < min_interval:
                wait_time = min_interval - elapsed
                await asyncio.sleep(wait_time)
                now = now + wait_time
            self._last_time = now
            return wait_time

    async def acquire_tokens(self, tokens_per_minute: int, token_count: int) -> float:
        """Acquire token permits for an estimated token_count; return wait time."""
        if tokens_per_minute <= 0 or token_count <= 0:
            return 0.0
        seconds_per_token = 60.0 / float(tokens_per_minute)
        required = seconds_per_token * float(token_count)
        async with self._lock:
            now = self.clock()
            elapsed = now - self._last_time
            wait_time = 0.0
            if elapsed < required:
                wait_time = required - elapsed
                await asyncio.sleep(wait_time)
                now = now + wait_time
            self._last_time = now
            return wait_time


@dataclass
class DualMicroLimiter:
    """Combines request and token limiting."""

    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        """Initialize internal micro-limiters."""
        self._request = MicroLimiter(self.clock)
        self._token = MicroLimiter(self.clock)

    async def acquire(
        self, constraint: RateConstraint, estimated_tokens: int
    ) -> dict[str, float]:
        """Acquire request and token permits; return wait breakdowns.

        Note: ``burst_factor`` is implemented as a simple multiplier on the
        configured requests-per-minute during short windows; it is not a full
        token-bucket shaper. This keeps enforcement predictable and simple.
        """
        waits = {"request": 0.0, "token": 0.0, "total": 0.0}
        if constraint.tokens_per_minute and estimated_tokens > 0:
            waits["token"] = await self._token.acquire_tokens(
                constraint.tokens_per_minute, estimated_tokens
            )
        # Apply burst factor by effectively increasing allowable rpm within short windows
        rpm = constraint.requests_per_minute
        if constraint.burst_factor and constraint.burst_factor > 1.0:
            rpm = int(rpm * float(constraint.burst_factor))
        waits["request"] = await self._request.acquire_request(rpm)

        if constraint.min_interval_ms > 0:
            min_interval = constraint.min_interval_ms / 1000.0
            if waits["request"] < min_interval:
                add = min_interval - waits["request"]
                await asyncio.sleep(add)
                waits["request"] += add

        waits["total"] = waits["token"] + waits["request"]
        return waits


type KeyExtractor = Callable[[PlannedCommand], tuple[str, ...]]


class RateLimitHandler(
    BaseAsyncHandler[PlannedCommand, PlannedCommand, RateLimitMiddlewareError]
):
    """Pipeline handler enforcing plan rate constraints."""

    def __init__(
        self,
        telemetry: TelemetryContextProtocol | None = None,
        key_extractor: KeyExtractor | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a rate limit middleware handler with optional telemetry and keying."""
        self._telemetry: TelemetryContextProtocol = telemetry or TelemetryContext()
        self._limiters: dict[tuple[str, ...], DualMicroLimiter] = {}
        self._extract_key: KeyExtractor = key_extractor or self._default_key_extractor
        self._clock = clock

    async def handle(
        self, command: PlannedCommand
    ) -> Result[PlannedCommand, RateLimitMiddlewareError]:
        """Enforce rate constraints for the given planned command then pass it through."""
        constraint = command.execution_plan.rate_constraint
        if constraint is None:
            return Success(command)

        key = self._extract_key(command)
        limiter = self._limiters.setdefault(key, DualMicroLimiter(self._clock))

        est_tokens = 0
        if command.token_estimate and constraint.tokens_per_minute:
            est_tokens = command.token_estimate.max_tokens

        with self._telemetry(
            "rate_limit.acquire", key="|".join(key), tokens=est_tokens
        ):
            waits = await limiter.acquire(constraint, est_tokens)

        if waits.get("total", 0.0) > 0:
            self._telemetry.metric(
                "rate_limit.wait_ms",
                int(waits["total"] * 1000),
                key="|".join(key),
                rpm=constraint.requests_per_minute,
                tpm=constraint.tokens_per_minute,
            )

        return Success(command)

    def _default_key_extractor(self, command: PlannedCommand) -> tuple[str, ...]:
        plan = command.execution_plan
        model = plan.calls[0].model_name
        provider = "unknown"
        lower = model.lower()
        if "gemini" in lower:
            provider = "gemini"
        elif "gpt" in lower:
            provider = "openai"
        elif "claude" in lower:
            provider = "anthropic"
        tier_value = "unknown"
        config = command.resolved.initial.config
        raw_tier = config.tier
        # Normalize enums to their value, otherwise str(). Explicitly check
        # for None so static checkers narrow the type before attribute access.
        if raw_tier is not None and hasattr(raw_tier, "value"):
            try:  # pragma: no cover - defensive only
                tier_value = str(raw_tier.value)
            except Exception:
                tier_value = str(raw_tier)
        else:
            tier_value = str(raw_tier)
        return (provider, model, tier_value)
