# ADR-0004: Middleware Pattern for Vendor-Neutral Rate Limiting

**Date:** 2025-08-13
**Status:** Accepted
**Tags:** rate-limiting, middleware, vendor-neutral, pipeline
**Audience:** Contributors and operators
**Impacted Modules/APIs:** `RateLimitHandler`, `RateConstraint` on `ExecutionPlan`, provider capability hooks

---

## Context

The original Pollux design embedded rate limiting in `GeminiClient.rate_limiter`. This approach:

- **Coupled rate limiting to client** — Hard to test independently
- **Used synchronous sleeps** — Blocked event loop
- **Lacked token awareness** — Only tracked request rate
- **Hidden in execution flow** — Not visible in pipeline
- **Provider-specific** — Gemini limits hardcoded

New requirements:

- Support multiple providers with different limit structures
- Allow user overrides without code changes
- Make rate limiting observable and debuggable
- Enable testing without real time delays

---

## Decision

Adopt a **middleware handler pattern** for rate limiting with:

1. **RateConstraint** — Immutable data in ExecutionPlan describing limits
2. **RateLimitHandler** — Pipeline handler enforcing constraints
3. **Micro-limiters** — Minimal timing enforcers with monotonic clock
4. **Provider capabilities** — Optional protocol for custom limits

### Key Elements

- Rate limits as pure data, not behavior
- Enforcement via pipeline handler, not embedded in client
- Dual limiters for requests + tokens
- Pluggable key extraction for custom scoping
- Structured telemetry for observability

### Implementation

```python
@dataclass(frozen=True)
class RateConstraint:
    requests_per_minute: int
    tokens_per_minute: int | None = None
    min_interval_ms: int = 0
    burst_factor: float = 1.0

class RateLimitHandler(BaseAsyncHandler[PlannedCommand, PlannedCommand, Never]):
    """Enforces rate constraints before API execution."""

    def __init__(self, key_extractor: KeyExtractor | None = None):
        self._limiters: dict[tuple, DualMicroLimiter] = {}
        self._extract_key = key_extractor or self._default_key_extractor

    async def handle(self, command: PlannedCommand) -> Result[PlannedCommand, Never]:
        constraint = self._extract_constraint(command)
        if not constraint:
            return Success(command)

        key = self._extract_key(command)
        limiter = self._limiters.setdefault(key, DualMicroLimiter())

        tokens = command.token_estimate.max_tokens if command.token_estimate else 0
        await limiter.acquire(constraint, tokens)

        return Success(command)
```

---

## Consequences

**Positive**:

- Clean separation of concerns
- Provider-agnostic enforcement
- Trivial to test with frozen time
- User overrides via configuration
- Observable via telemetry
- No global state

**Negative**:

- Extra handler in pipeline (minimal overhead)
- Micro-limiters not shared across processes
- Simple algorithm (no sophisticated shaping)

**Neutral**:

- Rate limiting visible in pipeline flow
- Requires ExecutionPlan modification

---

## Alternatives Considered

1. **Embedded limiter in APIHandler** — Rejected: couples concerns
2. **Global limiter registry** — Rejected: hidden state
3. **Adaptive token bucket** — Rejected: "magic" behavior
4. **Provider-specific handlers** — Rejected: proliferation of handlers
5. **External rate limit service** — Rejected: operational complexity

---

## Migration Path

1. Add `RateConstraint` to `core.types`
2. Extend `ExecutionPlan` with optional constraint
3. Implement `DualMicroLimiter` with tests
4. Create `RateLimitHandler`
5. Insert handler in pipeline
6. Migrate `core.models` limits to constraints
7. Add provider capability protocol
8. Enable user configuration overrides

---

## Validation Criteria

- Unit tests pass with frozen/mocked time
- No global state or singletons
- Rate limits visible in telemetry
- 429 errors eliminated in integration tests
- User overrides respected
- Provider limits correctly applied

---

## Operational Notes

- Align your environment tier settings (e.g., `POLLUX_TIER`) with actual billing/limits to avoid throttling or unexpected 429s.

---

## References

- [Concept — Rate Limiting](../concepts/rate-limiting.md)
- [Deep Dive — Rate Limiting Spec](../deep-dives/rate-limiting-spec.md)
- [Token Bucket Algorithm](https://en.wikipedia.org/wiki/Token_bucket)
