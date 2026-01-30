# Provider Capabilities Model — Conceptual Overview

> Status: Implemented. This model governs how provider differences are abstracted via adapter protocols.
>
> Audience: Contributors implementing new provider adapters.
> Prerequisites: Understanding of Python protocols and the API Execution pattern.

## Purpose & Scope

The Provider Capabilities Model defines how the pipeline abstracts over different LLM providers while maintaining type safety and explicit feature detection.

**In scope**:

- Capability protocol definitions
- Runtime capability checking
- Graceful degradation patterns
- Provider adapter structure

**Not in scope**:

- Specific provider API details
- Authentication/configuration
- Rate limiting strategies
- Pricing/quota management

---

## Design Forces

Different providers offer different features. The library exposes a neutral seam so features can be used when present and gracefully skipped when absent. The current codebase ships a Gemini adapter; other providers can be added by users.

Traditional approaches use:

- **Lowest common denominator**: Only features all providers support
- **Provider-specific branches**: If-else chains throughout code
- **Abstract base classes**: Complex inheritance hierarchies

We need:

- **Progressive enhancement**: Use features when available
- **Type safety**: Compile-time verification of capability usage
- **Runtime detection**: Graceful handling of missing features
- **Clear contracts**: Explicit about what each provider offers

---

## Core Concepts

### Capability Protocols

Fine-grained protocols define specific provider abilities (see `pollux.pipeline.adapters.base`):

```python
@runtime_checkable
class GenerationAdapter(Protocol):
    async def generate(*, model_name: str, api_parts: tuple[Any, ...], api_config: dict[str, object]) -> dict[str, Any]: ...

@runtime_checkable
class UploadsCapability(Protocol):
    async def upload_file_local(path: str | os.PathLike[str], mime_type: str | None) -> Any: ...

@runtime_checkable
class CachingCapability(Protocol):
    async def create_cache(*, model_name: str, content_parts: tuple[Any, ...], system_instruction: str | None, ttl_seconds: int | None) -> str: ...

@runtime_checkable
class ExecutionHintsAware(Protocol):
    def apply_hints(hints: Any) -> None: ...
```

### Capability Checking

Two levels of verification:

1. **Type-time**: Protocol conformance (via static typing where used)
2. **Runtime**: `isinstance()` checks enabled by `@runtime_checkable`

### Adapter Pattern

Each provider has an adapter that:

- Implements relevant capability protocols
- Translates between neutral and provider types
- Handles provider-specific errors
- Normalizes responses to a minimal raw dict consumed by the Result Builder

---

## Capability Hierarchy

At present, the execution seam defines these capabilities:

- Generation (required): `GenerationAdapter`
- Uploads (optional): `UploadsCapability`
- Context caching (optional): `CachingCapability`
- Hints (optional): `ExecutionHintsAware`

Additional capabilities can be added in the future as new protocols.

---

## Usage Patterns

### Required Capability

```python
# Generation is required - validate when accepting an adapter
if not isinstance(adapter, GenerationAdapter):
    raise ValueError("Adapter must support generation")
```

### Optional Capability

```python
# Uploads optional - check and degrade gracefully
if isinstance(adapter, UploadsCapability):
    file_ref = await adapter.upload_file_local(path, mime_type)
else:
    # Use inline content or skip
    pass
```

### Conditional Execution

```python
# Stage only runs if capability present
class UploadStage:
    def applies_to(self, state, adapter):
        return bool(state.plan.upload_tasks) and isinstance(adapter, UploadsCapability)
```

---

## Benefits

### Type Safety

- Can't call upload on provider without UploadsCapability
- IDE autocomplete shows available methods
- Type checker catches capability misuse

### Progressive Enhancement

- Use best features when available
- Degrade gracefully when not
- No artificial limitations

### Clear Contracts

- Adapters explicitly declare capabilities
- Users know what's available
- No hidden assumptions

### Testing

- Mock adapters can selectively implement capabilities
- Test graceful degradation paths
- Verify capability detection logic

---

## Anti-Patterns to Avoid

### ❌ Capability Assumption

```python
# Bad: Assumes all providers have upload
file_ref = await provider.upload_file(...)  # May not exist!
```

### ❌ Provider Name Checking

```python
# Bad: Brittle string checking
if "gemini" in provider_name.lower():
    # Use Gemini features
```

### ❌ Kitchen Sink Interface

```python
# Bad: One interface with everything optional
class Provider:
    async def generate(...)  # Required? Optional?
    async def upload(...)    # Raises NotImplementedError?
    async def cache(...)     # Returns None?
```

### ✅ Correct Pattern

```python
# Good: Explicit capability checking
if isinstance(provider, UploadsCapability):
    file_ref = await provider.upload_file(...)
else:
    # Explicit alternative path
    logger.info("Provider doesn't support uploads, using inline")
```

---

## Adding New Capabilities

1. Define a new protocol (e.g., in `pollux/pipeline/adapters/base.py` or a small adjacent module).
2. Mark it with `@runtime_checkable` for safe `isinstance` checks.
3. Implement it in relevant adapters.
4. Add conditional usage in the pipeline where appropriate.
5. Document graceful degradation behavior.
6. Add tests for both supported and unsupported paths.

---

## Related Documents

- [Concept — API Execution Pattern](./api-execution.md)
- [Deep Dive — API Handler Spec](../deep-dives/api-handler-spec.md)
- [How-to — Adding Provider Adapters](../../how-to/provider-adapters.md)
