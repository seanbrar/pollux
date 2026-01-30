# ADR-0003: Capability-Based API Handler with Pure Execution State

**Date:** 2025-08-13
**Status:** Accepted
**Tags:** api-handler, provider-abstraction, capabilities, execution-state
**Audience:** Contributors and adapter authors
**Impacted Modules/APIs:** API Handler, provider adapter capability protocols, execution state shape

---

## Context

The API Handler must execute `ExecutionPlan` objects against various provider SDKs (Gemini, OpenAI, Anthropic) while maintaining the pipeline's architectural principles.

Initial implementation mixed concerns:

- Execution state included telemetry and errors
- Single adapter handled all provider operations
- No clear boundary between required and optional features
- Provider differences handled via if-else branches

This violated key principles:

- **Data purity** — State mixed with observations
- **Single responsibility** — Adapters did too much
- **Explicit boundaries** — Optional features not clearly marked
- **Type safety** — No compile-time verification of capabilities

---

## Decision

Adopt a **capability-based provider model** with **pure execution state**:

### Key Elements

1. **Pure ExecutionState (conceptual)** — Contains only execution-relevant data; current implementation achieves this purity with local variables rather than a separate state object
2. **Capability Protocols** — Fine-grained, runtime-checkable protocols
3. **Self-limiting Stages** — Stages that refuse inappropriate work; uploads can be inferred from `FilePlaceholder` parts when explicit tasks are absent
4. **Orthogonal Telemetry** — Observation separate from execution

### Architecture

```python
# Pure state
@dataclass(frozen=True)
class ExecutionState:
    plan: ExecutionPlan
    parts: tuple[APIPart, ...]
    cache_reference: CacheReference | None = None

# Capability protocols
@runtime_checkable
class GenerationCapability(Protocol):
    async def generate(...) -> dict: ...

@runtime_checkable
class UploadsCapability(Protocol):
    async def upload_file(...) -> FileRefPart: ...

# Self-limiting stages
class UploadStage:  # conceptual example
    def applies_to(self, state: ExecutionState) -> bool:
        return bool(state.plan.upload_tasks)

    async def execute(self, state, provider) -> ExecutionState:
        if not isinstance(provider, UploadsCapability):
            return state  # Skip if not supported
        # ... perform uploads ...
```

---

## Consequences

### Positive

- **Type safety**: Can't call unsupported operations
- **Clear degradation**: Explicit handling of missing capabilities
- **Pure transformations**: State changes are traceable
- **Test isolation**: Each capability independently mockable
- **Future-proof**: New providers just implement protocols

### Negative

- **More protocols**: Additional abstraction layer
- **Runtime checks**: Some verification happens at runtime
- **Learning curve**: Developers must understand capability model

### Neutral

- Providers explicitly declare what they support
- Optional features require conditional code paths
- Telemetry becomes a cross-cutting concern

---

## Alternatives Considered

### Alternative 1: Single Adapter Interface

All methods on one interface, with `NotImplementedError` for unsupported operations.

- ❌ Runtime failures for unsupported operations
- ❌ Unclear which operations are required vs optional
- ❌ Poor IDE support and type checking

### Alternative 2: Provider Subclasses

Abstract base class with provider-specific subclasses.

- ❌ Rigid inheritance hierarchy
- ❌ Difficult to mix capabilities
- ❌ Encourages feature creep in base class

### Alternative 3: Feature Flags

Configuration flags indicating supported features.

- ❌ Decouples capability from implementation
- ❌ No type safety
- ❌ Easy to misconfigure

---

## Implementation Plan

### Phase 1: Core Structure (Week 1)

- [x] Pure ExecutionState dataclass
- [x] Capability protocols
- [x] Basic GeminiAdapter with all capabilities
- [x] MockAdapter for testing

### Phase 2: Stages (Week 1-2)

- [ ] UploadStage with capability checking
- [ ] CacheStage with graceful degradation
- [ ] Fallback execution logic

### Phase 3: Additional Providers (Week 2-3)

- [ ] OpenAIAdapter (generation only)
- [ ] AnthropicAdapter (generation + caching)
- [ ] Capability detection tests

### Phase 4: Telemetry (Week 3)

- [ ] Orthogonal TelemetryCollector
- [ ] Token validation helpers
- [ ] Metrics aggregation

---

## Validation Criteria

- All existing tests pass with new handler
- Capability checks prevent invalid operations
- Telemetry doesn't affect execution flow
- New providers addable without core changes
- Type checker catches capability misuse

---

## References

- [Concept — API Execution Pattern](../concepts/api-execution.md)
- [Concept — Provider Capabilities](../concepts/provider-capabilities.md)
- [Architecture Rubric](../architecture-rubric.md)
- [ADR-0001 — Command Pipeline](./ADR-0001-command-pipeline.md)

---

## Code Examples

### Adding a New Provider

```python
class AnthropicAdapter:
    """Anthropic with generation and caching, no uploads."""

    # Only implement supported capabilities
    async def generate(self, ...) -> dict:
        # Anthropic-specific generation
        pass

    async def create_cache(self, ...) -> CacheReference:
        # Anthropic caching approach
        pass

    # No upload_file method - not supported
```

### Using in Pipeline

```python
# Provider capabilities detected automatically
provider = AnthropicAdapter(api_key="...")
handler = APIHandler(provider=provider)

# Upload stage will skip (no UploadsCapability)
# Cache stage will run (has CachingCapability)
# Generation always runs (required capability)
result = await handler.handle(planned_command)
```
