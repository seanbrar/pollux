# Rate Limiting — Technical Specification

> Status: Target state. Implementation follows middleware pattern with micro-limiters.

## 1. Overview

This document specifies the technical implementation of vendor-neutral rate limiting via pipeline middleware. The design emphasizes simplicity, testability, and clean provider integration.

---

## 2. Core Data Types

### Rate Constraint

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class RateConstraint:
    """Immutable rate limit specification.

    All rates are per-minute. The handler converts to per-second internally.
    """
    requests_per_minute: int
    tokens_per_minute: int | None = None
    min_interval_ms: int = 0  # Minimum time between requests
    burst_factor: float = 1.0  # Allow bursts up to factor * rate

    def __post_init__(self):
        if self.requests_per_minute <= 0:
            object.__setattr__(self, 'requests_per_minute', 1)
        if self.tokens_per_minute is not None and self.tokens_per_minute <= 0:
            object.__setattr__(self, 'tokens_per_minute', None)
        if self.burst_factor < 1.0:
            object.__setattr__(self, 'burst_factor', 1.0)
```

### Updated ExecutionPlan

```python
@dataclass(frozen=True)
class ExecutionPlan:
    primary_call: APICall
    fallback_call: APICall | None = None
    rate_constraint: RateConstraint | None = None  # NEW
    upload_tasks: tuple[UploadTask, ...] = ()
    explicit_cache: ExplicitCache | None = None
```

---

## 3. Micro-Limiter Implementation

### Single Limiter

```python
import time
import asyncio

class MicroLimiter:
    """Minimal rate limiter using monotonic clock.

    Thread-safe for single-process use. No cross-process coordination.
    """

    def __init__(self, clock=time.monotonic):
        self._last_time: float = 0.0
        self._clock = clock  # Injectable for testing

    async def acquire_request(self, requests_per_minute: int) -> float:
        """Acquire single request permit. Returns wait time in seconds."""
        if requests_per_minute <= 0:
            return 0.0

        min_interval = 60.0 / requests_per_minute
        now = self._clock()
        elapsed = now - self._last_time

        wait_time = 0.0
        if elapsed < min_interval:
            wait_time = min_interval - elapsed
            await asyncio.sleep(wait_time)
            now = self._clock()

        self._last_time = now
        return wait_time

    async def acquire_tokens(self, tokens_per_minute: int, token_count: int) -> float:
        """Acquire token permits. Returns wait time in seconds."""
        if tokens_per_minute <= 0 or token_count <= 0:
            return 0.0

        seconds_per_token = 60.0 / tokens_per_minute
        required_time = seconds_per_token * token_count

        now = self._clock()
        elapsed = now - self._last_time

        wait_time = 0.0
        if elapsed < required_time:
            wait_time = required_time - elapsed
            await asyncio.sleep(wait_time)
            now = self._clock()

        self._last_time = now
        return wait_time
```

### Dual Limiter

```python
class DualMicroLimiter:
    """Combines request and token rate limiting."""

    def __init__(self, clock=time.monotonic):
        self._request_limiter = MicroLimiter(clock)
        self._token_limiter = MicroLimiter(clock)

    async def acquire(
        self,
        constraint: RateConstraint,
        estimated_tokens: int = 0
    ) -> dict[str, float]:
        """Acquire permits per constraint. Returns wait times."""
        waits = {"request": 0.0, "token": 0.0, "total": 0.0}

        # Token limiter first (provides backpressure)
        if constraint.tokens_per_minute and estimated_tokens > 0:
            waits["token"] = await self._token_limiter.acquire_tokens(
                constraint.tokens_per_minute, estimated_tokens
            )

        # Then request limiter
        waits["request"] = await self._request_limiter.acquire_request(
            constraint.requests_per_minute
        )

        # Enforce minimum interval if specified
        if constraint.min_interval_ms > 0:
            min_interval = constraint.min_interval_ms / 1000.0
            if waits["request"] < min_interval:
                additional_wait = min_interval - waits["request"]
                await asyncio.sleep(additional_wait)
                waits["request"] += additional_wait

        waits["total"] = waits["token"] + waits["request"]
        return waits
```

---

## 4. Rate Limit Handler

```python
from typing import Callable, Protocol
from pollux.pipeline.base import BaseAsyncHandler
from pollux.telemetry import TelemetryContextProtocol

# Type for key extraction
KeyExtractor = Callable[[PlannedCommand], tuple[str, ...]]

class RateLimitHandler(BaseAsyncHandler[PlannedCommand, PlannedCommand, Never]):
    """Pipeline handler that enforces rate constraints.

    Maintains micro-limiters per extracted key (default: provider, model, tier).
    Emits detailed telemetry for observability.
    """

    def __init__(
        self,
        telemetry: TelemetryContextProtocol | None = None,
        key_extractor: KeyExtractor | None = None,
        clock=time.monotonic
    ):
        self._telemetry = telemetry or TelemetryContext()
        self._limiters: dict[tuple, DualMicroLimiter] = {}
        self._extract_key = key_extractor or self._default_key_extractor
        self._clock = clock

    async def handle(self, command: PlannedCommand) -> Result[PlannedCommand, Never]:
        """Enforce rate constraints then forward command."""
        # Extract constraint from plan
        constraint = self._extract_constraint(command)
        if not constraint:
            # No limiting needed
            return Success(command)

        # Get or create limiter for this key
        key = self._extract_key(command)
        limiter = self._limiters.setdefault(key, DualMicroLimiter(self._clock))

        # Calculate tokens to reserve
        tokens = 0
        if command.token_estimate and constraint.tokens_per_minute:
            tokens = command.token_estimate.max_tokens

        # Acquire permits (may sleep)
        with self._telemetry("rate_limit.acquire", key=key, tokens=tokens):
            waits = await limiter.acquire(constraint, tokens)

        # Emit detailed telemetry
        if waits["total"] > 0:
            self._telemetry.event("rate_limit.delayed", {
                "limiter_key": key,
                "wait_ms": int(waits["total"] * 1000),
                "request_wait_ms": int(waits["request"] * 1000),
                "token_wait_ms": int(waits["token"] * 1000),
                "estimated_tokens": tokens,
                "constraint": {
                    "rpm": constraint.requests_per_minute,
                    "tpm": constraint.tokens_per_minute
                }
            })

        return Success(command)

    def _extract_constraint(self, command: PlannedCommand) -> RateConstraint | None:
        """Extract rate constraint from execution plan."""
        return command.execution_plan.rate_constraint

    def _default_key_extractor(self, command: PlannedCommand) -> tuple[str, ...]:
        """Default: key by (provider, model, tier)."""
        plan = command.execution_plan
        model = plan.primary_call.model_name

        # Infer provider from model name
        provider = "unknown"
        if "gemini" in model.lower():
            provider = "gemini"
        elif "gpt" in model.lower():
            provider = "openai"
        elif "claude" in model.lower():
            provider = "anthropic"

        # Extract tier from config if available
        tier = "unknown"
        config = command.resolved.initial.config
        if isinstance(config, dict):
            tier = config.get("tier", "unknown")

        return (provider, model, str(tier))
```

---

## 5. Provider Integration

### Provider Capability (Optional)

```python
class RateLimitCapability(Protocol):
    """Optional protocol for providers to supply custom rate constraints."""

    def get_rate_constraint(
        self,
        model: str,
        config: dict[str, Any]
    ) -> RateConstraint | None:
        """Return rate constraint for model/config combination.

        Returns None if no specific limits are known.
        """
        ...
```

### Gemini Provider Implementation

```python
from pollux.client.models import APITier, get_rate_limits

class GeminiRateLimitCapability:
    """Gemini-specific rate limit provider."""

    def get_rate_constraint(
        self,
        model: str,
        config: dict[str, Any]
    ) -> RateConstraint | None:
        # Check for user override
        if "rate_limits" in config:
            limits = config["rate_limits"]
            return RateConstraint(
                requests_per_minute=limits.get("requests_per_minute", 60),
                tokens_per_minute=limits.get("tokens_per_minute")
            )

        # Use tier-based limits
        tier_str = config.get("tier", "free")
        try:
            tier = APITier[tier_str.upper()]
        except KeyError:
            tier = APITier.FREE

        limits = get_rate_limits(tier, model)
        if limits:
            return RateConstraint(
                requests_per_minute=limits.requests_per_minute,
                tokens_per_minute=limits.tokens_per_minute
            )

        # Fallback
        return RateConstraint(requests_per_minute=10)
```

### Integration in Planner

```python
class ExecutionPlanner(BaseHandler[ResolvedCommand, PlannedCommand]):

    def handle(self, command: ResolvedCommand) -> PlannedCommand:
        # ... existing planning logic ...

        # Add rate constraint to plan
        constraint = self._get_rate_constraint(command)
        plan = ExecutionPlan(
            primary_call=primary,
            fallback_call=fallback,
            rate_constraint=constraint  # NEW
        )

        return PlannedCommand(
            resolved=command,
            execution_plan=plan,
            token_estimate=estimate
        )

    def _get_rate_constraint(self, command: ResolvedCommand) -> RateConstraint | None:
        """Resolve rate constraint for command."""
        config = command.initial.config
        model = config.get("model", "gemini-2.0-flash")

        # Try provider capability first
        provider = self._get_provider(model)
        if hasattr(provider, 'get_rate_constraint'):
            constraint = provider.get_rate_constraint(model, config)
            if constraint:
                return constraint

        # Fallback to static data
        if "gemini" in model.lower():
            capability = GeminiRateLimitCapability()
            return capability.get_rate_constraint(model, config)

        # Default constraint
        return RateConstraint(requests_per_minute=60)
```

---

## 6. Testing Strategy

### Unit Tests

```python
import asyncio
from unittest.mock import Mock

class TestMicroLimiter:

    async def test_no_delay_for_first_request(self):
        clock = Mock(side_effect=[0.0, 0.0])
        limiter = MicroLimiter(clock)

        wait = await limiter.acquire_request(60)  # 1 per second
        assert wait == 0.0
        assert clock.call_count == 2

    async def test_delay_for_rapid_requests(self):
        times = [0.0, 0.0, 0.5, 0.5]  # Second request at 0.5s
        clock = Mock(side_effect=times)
        limiter = MicroLimiter(clock)

        # First request
        await limiter.acquire_request(60)

        # Second request (should wait 0.5s)
        with patch('asyncio.sleep') as mock_sleep:
            wait = await limiter.acquire_request(60)
            mock_sleep.assert_called_once_with(0.5)
            assert wait == 0.5

class TestRateLimitHandler:

    async def test_passthrough_without_constraint(self):
        handler = RateLimitHandler()
        command = PlannedCommand(
            resolved=...,
            execution_plan=ExecutionPlan(
                primary_call=...,
                rate_constraint=None  # No constraint
            )
        )

        result = await handler.handle(command)
        assert isinstance(result, Success)
        assert result.value is command

    async def test_enforcement_with_constraint(self):
        clock = Mock(side_effect=[0.0, 0.0, 0.0])
        handler = RateLimitHandler(clock=clock)

        command = PlannedCommand(
            resolved=...,
            execution_plan=ExecutionPlan(
                primary_call=...,
                rate_constraint=RateConstraint(
                    requests_per_minute=60,
                    tokens_per_minute=1000
                )
            ),
            token_estimate=TokenEstimate(
                min_tokens=100,
                expected_tokens=100,
                max_tokens=100
            )
        )

        with patch('asyncio.sleep'):
            result = await handler.handle(command)
            assert isinstance(result, Success)
```

### Integration Tests

```python
class TestPipelineWithRateLimiting:

    async def test_full_pipeline_with_limits(self):
        """Verify rate limiting in complete pipeline."""
        handlers = [
            SourceHandler(),
            ExecutionPlanner(),
            RateLimitHandler(),  # Inserted here
            APIHandler(),
            ResultBuilder()
        ]

        executor = GeminiExecutor(handlers=handlers)
        command = InitialCommand(
            sources=["test.txt"],
            config={"rate_limits": {"requests_per_minute": 120}}
        )

        result = await executor.execute(command)
        assert result.status == "ok"

        # Verify constraint was applied
        telemetry = result.telemetry_data
        assert "rate_limit.acquire" in telemetry
```

### Property Tests

```python
from hypothesis import given, strategies as st

class TestRateLimitProperties:

    @given(
        rpm=st.integers(min_value=1, max_value=10000),
        requests=st.integers(min_value=1, max_value=100)
    )
    async def test_rate_never_exceeded(self, rpm, requests):
        """Verify actual rate never exceeds configured limit."""
        clock = MonotonicClock()
        limiter = MicroLimiter(clock)

        start = clock.time()
        for _ in range(requests):
            await limiter.acquire_request(rpm)
        end = clock.time()

        elapsed = end - start
        actual_rate = requests / (elapsed / 60) if elapsed > 0 else float('inf')

        assert actual_rate <= rpm * 1.01  # Allow 1% tolerance
```

---

## 7. Configuration

### User Configuration

```yaml
# config.yaml
gemini:
  model: gemini-2.0-flash
  tier: tier_2
  rate_limits:
    requests_per_minute: 1000  # Override default
    tokens_per_minute: 4000000
    min_interval_ms: 100  # Space out requests
```

### Programmatic Configuration

```python
client = GeminiClient(
    rate_limits={
        "requests_per_minute": 500,
        "tokens_per_minute": 2000000
    }
)

# Or with custom key extraction
def per_user_key(command: PlannedCommand) -> tuple[str, ...]:
    user_id = command.resolved.initial.config.get("user_id", "default")
    return ("user", user_id)

executor = GeminiExecutor(
    handlers=[
        RateLimitHandler(key_extractor=per_user_key),
        # ...
    ]
)
```

---

## 8. Telemetry & Observability

### Emitted Events

```python
# Rate limit acquisition
{
    "event": "rate_limit.acquire",
    "timestamp": 1234567890.123,
    "attributes": {
        "limiter_key": ("gemini", "gemini-2.0-flash", "tier_2"),
        "estimated_tokens": 1500
    }
}

# Delay applied
{
    "event": "rate_limit.delayed",
    "timestamp": 1234567890.456,
    "data": {
        "limiter_key": ("gemini", "gemini-2.0-flash", "tier_2"),
        "wait_ms": 250,
        "request_wait_ms": 50,
        "token_wait_ms": 200,
        "estimated_tokens": 1500,
        "constraint": {
            "rpm": 1000,
            "tpm": 4000000
        }
    }
}
```

### Metrics

- `rate_limit.acquisitions` - Counter of permit acquisitions
- `rate_limit.delays` - Counter of delayed requests
- `rate_limit.wait_time` - Histogram of wait times
- `rate_limit.tokens_reserved` - Histogram of tokens reserved

---

## 9. Migration Checklist

- [ ] Add `RateConstraint` to `core/types.py`
- [ ] Extend `ExecutionPlan` with `rate_constraint` field
- [ ] Implement `MicroLimiter` with tests
- [ ] Implement `DualMicroLimiter` with tests
- [ ] Create `RateLimitHandler`
- [ ] Add handler to pipeline configuration
- [ ] Implement `GeminiRateLimitCapability`
- [ ] Update planner to set constraints
- [ ] Add telemetry events
- [ ] Document user configuration
- [ ] Add integration tests
- [ ] Update examples

---

## 10. References

- [Concept — Rate Limiting](../concepts/rate-limiting.md)
- [ADR-0004 — Rate Limiting Pattern](../decisions/ADR-0004-rate-limiting.md)
- [Command Pipeline Architecture](./command-pipeline-spec.md)
- [Gemini API Rate Limits](https://ai.google.dev/gemini-api/docs/rate-limits)
!!! note "Draft – pending revision"
    This specification will be reworked for clarity and efficacy. Included in nav for discoverability; content to be reviewed before release.

Last reviewed: 2025-09
