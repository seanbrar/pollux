# API Handler — Technical Specification

> Status: Implemented (MVP). This specification defines the technical architecture for API execution.
>
> Audience: Contributors implementing or extending the API handler.
> Prerequisites: Understanding of the Command Pipeline, async Python, and Protocol types.

## 1. Overview

The API Handler executes `PlannedCommand` objects against provider SDKs, returning `FinalizedCommand` objects. It uses pure state transformations, capability-based provider abstraction, and orthogonal telemetry.

---

## 2. Core Types

### Execution State (conceptual)

```python
@dataclass(frozen=True)
class ExecutionState:
    """Pure execution state - immutable and focused."""
    plan: ExecutionPlan
    parts: tuple[APIPart, ...]
    cache_reference: CacheReference | None = None

    # Transform methods return new instances
    def with_parts(self, parts: tuple[APIPart, ...]) -> "ExecutionState"
    def with_cache(self, ref: CacheReference) -> "ExecutionState"
```

### Cache Reference

```python
@dataclass(frozen=True)
class CacheReference:
    """Provider-neutral cache identifier."""
    cache_id: str
    created_at: float
    expires_at: float | None = None
```

Implementation note: The current code achieves the same purity and immutability using local variables within the handler rather than materializing a separate `ExecutionState` object. This reduces ceremony while keeping behavior explicit.

---

## 3. Capability Protocols

### Required Capability

```python
@runtime_checkable
class GenerationCapability(Protocol):
    """All providers must implement generation."""

    async def generate(
        self,
        model: str,
        parts: tuple[APIPart, ...],
        config: dict[str, Any],
        cache_ref: CacheReference | None = None
    ) -> dict[str, Any]:
        """Execute generation and return normalized response."""
        ...
```

### Optional Capabilities

```python
@runtime_checkable
class UploadsCapability(Protocol):
    """Optional file upload support."""

    async def upload_file(
        self,
        path: Path,
        mime_type: str | None
    ) -> FileRefPart:
        """Upload file and return reference."""
        ...

@runtime_checkable
class CachingCapability(Protocol):
    """Optional context caching support."""

    async def create_cache(
        self,
        model: str,
        contents: tuple[APIPart, ...],
        ttl_seconds: int = 3600
    ) -> CacheReference:
        """Create cache and return reference."""
        ...

    async def get_cache(
        self,
        cache_id: str
    ) -> CacheReference | None:
        """Retrieve existing cache reference."""
        ...
```

---

## 4. Execution Stages

### Stage Protocol

```python
class ExecutionStage(Protocol):
    """Protocol for all execution stages."""

    def applies_to(self, state: ExecutionState) -> bool:
        """Check if stage should run for given state."""
        ...

    async def execute(
        self,
        state: ExecutionState,
        provider: Any
    ) -> ExecutionState:
        """Execute stage, returning new state."""
        ...
```

### Stage Implementations (conceptual)

```python
@dataclass
class UploadStage:
    """Handles file uploads if present and supported."""

    def applies_to(self, state: ExecutionState) -> bool:
        return bool(state.plan.upload_tasks)

    async def execute(
        self,
        state: ExecutionState,
        provider: Any
    ) -> ExecutionState:
        # Check capability
        if not isinstance(provider, UploadsCapability):
            if any(task.required for task in state.plan.upload_tasks):
                raise APIError("Required uploads not supported")
            return state

        # Perform uploads in parallel
        parts = list(state.parts)
        tasks = []
        for task in state.plan.upload_tasks:
            if task.local_path:
                tasks.append(self._upload_and_substitute(
                    provider, task, parts
                ))

        await asyncio.gather(*tasks)
        return state.with_parts(tuple(parts))
```

---

## 5. Provider Adapters

### Base Structure

```python
class BaseProviderAdapter:
    """Base for all provider adapters."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = self._initialize_client()

    @abstractmethod
    def _initialize_client(self) -> Any:
        """Initialize provider SDK client."""
        ...

    def _normalize_response(self, response: Any) -> dict[str, Any]:
        """Convert provider response to standard format."""
        return {
            "text": self._extract_text(response),
            "model": self._extract_model(response),
            "usage": self._extract_usage(response),
            "metadata": self._extract_metadata(response)
        }
```

Implementation note: Upload, cache, and generation are executed in small, self-limiting sections of the handler. Uploads are inferred from `FilePlaceholder` parts when `UploadTask` is absent.

### Gemini Adapter Example

```python
class GeminiAdapter(BaseProviderAdapter):
    """Gemini with full capability support."""

    def _initialize_client(self) -> Any:
        import google.genai as genai
        return genai.Client(self.api_key)

    # Implement all capabilities
    async def generate(self, ...) -> dict[str, Any]:
        # Gemini-specific generation
        pass

    async def upload_file(self, ...) -> FileRefPart:
        # Use Gemini Files API
        pass

    async def create_cache(self, ...) -> CacheReference:
        # Use Gemini caching
        pass
```

---

## 6. Telemetry Collection

### Orthogonal Collection

```python
@dataclass
class TelemetryCollector:
    """Collects metrics without affecting execution."""
    metrics: dict[str, Any] = field(default_factory=dict)

    @asynccontextmanager
    async def measure(self, operation: str):
        """Measure operation duration."""
        start = time.perf_counter()
        try:
            yield self
        finally:
            duration = time.perf_counter() - start
            self.metrics[f"{operation}_duration_ms"] = duration * 1000

    def add_metric(self, key: str, value: Any) -> None:
        """Add a metric value."""
        self.metrics[key] = value
```

### Token Validation

```python
def validate_tokens(
    response: dict[str, Any],
    estimate: TokenEstimate
) -> dict[str, Any]:
    """Validate actual vs estimated tokens."""
    usage = response.get("usage", {})
    actual = usage.get("total_token_count", 0)

    return {
        "estimated": {
            "min": estimate.min_tokens,
            "expected": estimate.expected_tokens,
            "max": estimate.max_tokens
        },
        "actual": actual,
        "in_range": estimate.min_tokens <= actual <= estimate.max_tokens,
        "accuracy_ratio": (
            actual / estimate.expected_tokens
            if estimate.expected_tokens > 0
            else 0
        )
    }
```

---

## 7. Error Handling

### Error Types

```python
class APIError(Exception):
    """Base API error."""
    pass

class CapabilityError(APIError):
    """Required capability not available."""
    pass

class ProviderError(APIError):
    """Provider-specific error."""

    def __init__(self, message: str, provider: str, original: Exception):
        super().__init__(message)
        self.provider = provider
        self.original = original
```

### Fallback Execution

```python
async def execute_with_fallback(
    handler: APIHandler,
    command: PlannedCommand
) -> Result[FinalizedCommand, APIError]:
    """Execute with fallback on failure."""

    # Try primary
    result = await handler.handle(command)

    if isinstance(result, Failure) and command.execution_plan.fallback_call:
        # Create fallback command
        fallback_plan = ExecutionPlan(
            primary_call=command.execution_plan.fallback_call,
            # Simplified - no uploads/caching for fallback
            upload_tasks=(),
            explicit_cache=None
        )

        fallback_command = replace(
            command,
            execution_plan=fallback_plan
        )

        # Try fallback
        fallback_result = await handler.handle(fallback_command)

        # Add fallback telemetry
        if isinstance(fallback_result, Success):
            fallback_result.value.telemetry_data["used_fallback"] = True
            fallback_result.value.telemetry_data["primary_error"] = str(result.error)

        return fallback_result

    return result
```

---

## 8. Testing Strategy

### Unit Tests

```python
def test_execution_state_immutability():
    """State transformations don't mutate."""
    state1 = ExecutionState(plan=mock_plan, parts=())
    state2 = state1.with_parts((TextPart("new"),))

    assert state1.parts == ()
    assert state2.parts == (TextPart("new"),)
    assert state1 is not state2

def test_capability_detection():
    """Capabilities detected correctly."""
    full_provider = GeminiAdapter("key")
    basic_provider = OpenAIAdapter("key")

    assert isinstance(full_provider, GenerationCapability)
    assert isinstance(full_provider, UploadsCapability)
    assert isinstance(full_provider, CachingCapability)

    assert isinstance(basic_provider, GenerationCapability)
    assert not isinstance(basic_provider, UploadsCapability)
```

### Integration Tests

```python
async def test_upload_stage_with_capability():
    """Upload stage runs when capability present."""
    provider = GeminiAdapter("key")
    stage = UploadStage()
    state = ExecutionState(
        plan=plan_with_uploads,
        parts=(TextPart("text"), FilePlaceholder(0))
    )

    new_state = await stage.execute(state, provider)

    assert isinstance(new_state.parts[1], FileRefPart)

async def test_upload_stage_without_capability():
    """Upload stage skips when capability absent."""
    provider = OpenAIAdapter("key")  # No uploads
    stage = UploadStage()
    state = ExecutionState(
        plan=plan_with_optional_uploads,
        parts=(TextPart("text"),)
    )

    new_state = await stage.execute(state, provider)

    assert new_state == state  # Unchanged
```

---

## 9. Performance Considerations

### Parallel Operations

- Upload multiple files concurrently
- Cache creation can overlap with other prep
- Use `asyncio.gather()` for independent operations

### State Size

- ExecutionState kept minimal
- Large content in parts, not state
- Telemetry separate from execution

### Provider Calls

- Single generation call per execution
- Reuse cached content when available
- Respect rate limits via a dedicated `RateLimitHandler` positioned before the API handler

---

## 10. Migration Path

### From Legacy APIHandler

```python
# Before: Mixed concerns
class APIHandler:
    def handle(self, command):
        # Uploads, caching, generation, telemetry all mixed
        ...

# After: Separated concerns
class APIHandler:
    def handle(self, command):
        state = ExecutionState(...)
        for stage in self.stages:
            if stage.applies_to(state):
                state = await stage.execute(state, provider)
        # Generate and return
```

### Adding New Provider

1. Create adapter implementing capabilities
2. Add to `adapters/` directory
3. Register in adapter factory
4. Add provider-specific tests
5. Document capability support

---

## Related Documents

- [Concept — API Execution Pattern](../concepts/api-execution.md)
- [Concept — Provider Capabilities](../concepts/provider-capabilities.md)
- [ADR-0003 — API Handler Architecture](../decisions/ADR-0003-api-handler.md)
!!! note "Draft – pending revision"
    This specification will be reworked for clarity and efficacy. Included in nav for discoverability; content to be reviewed before release.

Last reviewed: 2025-09
