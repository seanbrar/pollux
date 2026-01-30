# Result Builder – Technical Specification

> Status: Implemented. Defines the technical architecture for result extraction and packaging.
>
> Audience: Contributors implementing or extending the Result Builder.
> Prerequisites: Understanding of the Command Pipeline, Python typing, and pure functions.

## 1. Overview

The Result Builder implements a Two-Tier Transform Chain that converts `FinalizedCommand` objects into stable result envelopes. It uses pure transforms with explicit priorities, an infallible fallback, and record-only validation to achieve 100% extraction success rate.

---

## 2. Core Types

### Transform Specification

```python
@dataclass(frozen=True)
class TransformSpec:
    """Pure extraction transform specification.

    Guarantees:
    - matcher and extractor are pure functions
    - No I/O or side effects
    - Deterministic for same input
    """
    name: str
    matcher: Callable[[Any], bool]  # Predicate: should this transform run?
    extractor: Callable[[Any, dict[str, Any]], dict[str, Any]]  # Pure transform
    priority: int = 0  # Higher priority runs first

    def __post_init__(self):
        if not callable(self.matcher) or not callable(self.extractor):
            raise ValueError(f"Transform {self.name}: matcher/extractor must be callable")
```

### Extraction Context

```python
@dataclass(frozen=True)
class ExtractionContext:
    """Immutable context passed to extractors."""
    expected_count: int = 1  # Number of answers expected
    schema: Any | None = None  # Optional Pydantic schema
    config: dict[str, Any] = field(default_factory=dict)
    prompts: tuple[str, ...] = ()  # Original prompts for reference
```

### Extraction Contract

```python
@dataclass(frozen=True)
class Violation:
    """Single contract violation."""
    message: str
    severity: Literal["info", "warning", "error"] = "warning"

@dataclass(frozen=True)
class ExtractionContract:
    """Record-only contract - violations never fail extraction."""
    answer_count: int | None = None
    min_answer_length: int = 0
    max_answer_length: int = 100_000
    required_fields: frozenset[str] = frozenset()

    def validate(self, result: dict[str, Any]) -> list[Violation]:
        """Check contract, return violations for telemetry."""
        violations: list[Violation] = []
        # ... validation logic that records but doesn't raise
        return violations
```

### Result Envelope

```python
class ResultEnvelope(TypedDict, total=False):
    """Stable result shape for all extractions."""
    status: Literal["ok", "partial", "error"]  # End-to-end status
    answers: list[str]  # Always present, padded if needed
    extraction_method: str  # Which transform/fallback succeeded
    confidence: float  # 0.0-1.0 extraction confidence
    structured_data: Any  # Original structured data if available
    metrics: dict[str, Any]  # Telemetry metrics
    usage: dict[str, Any]  # Token usage data
    diagnostics: dict[str, Any]  # When diagnostics enabled
    validation_warnings: tuple[str, ...]  # Schema/contract violations
```

Note: The presence and range of `confidence` are enforced centrally by the
core ResultEnvelope validator. Envelopes must include `confidence` and its
value must be within [0.0, 1.0]. Custom terminal stages should construct
valid envelopes up-front; invalid envelopes fail fast at the executor/consumer
seam via the shared validator.

---

## 3. Transform Implementation

### Built-in Transforms

```python
def json_array_transform() -> TransformSpec:
    """Extract from JSON arrays (with markdown unwrapping)."""

    def matcher(raw: Any) -> bool:
        text = _get_text(raw)
        if not text:
            return False
        s = text.strip()
        return s.startswith("[") or "```json" in s or s.startswith("```")

    def extractor(raw: Any, ctx: dict[str, Any]) -> dict[str, Any]:
        text = _get_text(raw)
        # Handle markdown fencing
        if "```json" in text:
            text = text.split("```json", 1)[1].rsplit("```", 1)[0]
        elif text.startswith("```"):
            text = text.split("```", 2)[1]

        data = json.loads(text.strip())
        if not isinstance(data, list):
            raise ValueError("Not a JSON array")

        # Normalize nulls to empty strings
        answers = ["" if x is None else str(x) for x in data]

        return {
            "answers": answers,
            "confidence": 0.95,
            "structured_data": data
        }

    return TransformSpec(
        name="json_array",
        matcher=matcher,
        extractor=extractor,
        priority=90
    )
```

### Provider Normalized Transform

```python
def provider_normalized_transform() -> TransformSpec:
    """Handle pre-normalized provider shapes (soft IR pattern)."""

    # Expected shape:
    # {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}

    def matcher(raw: Any) -> bool:
        return isinstance(raw, dict) and "candidates" in raw

    def extractor(raw: Any, ctx: dict[str, Any]) -> dict[str, Any]:
        # Navigate defensive - providers vary
        candidates = raw.get("candidates", [])
        if not candidates:
            raise ValueError("No candidates")

        # Extract text from nested structure
        text = None
        for part in candidates[0].get("content", {}).get("parts", []):
            if isinstance(part, dict) and "text" in part:
                text = part["text"]
                break

        if text is None:
            raise ValueError("No text found in candidates")

        return {
            "answers": [str(text)],
            "confidence": 0.9
        }

    return TransformSpec(
        name="provider_normalized",
        matcher=matcher,
        extractor=extractor,
        priority=80
    )
```

### Batch Response Transform

Handles the library's internal vectorized container shape produced by the API handler:

```python
def batch_response_transform() -> TransformSpec:
    """Extract answers from internal batch response format: {'batch': [...]}"""

    def matcher(raw: Any) -> bool:
        return isinstance(raw, dict) and isinstance(raw.get("batch"), (list, tuple)) and raw["batch"]

    def extractor(raw: Any, _ctx: dict[str, Any]) -> dict[str, Any]:
        def coerce(item: Any) -> str:
            match item:
                case str() as txt:
                    return txt
                case {"text": str(txt)} | {"content": str(txt)} | {"answer": str(txt)} | {"response": str(txt)} | {"message": str(txt)}:
                    return txt
                case {"candidates": [{"content": {"parts": [{"text": str(txt)}, *rest]}} , *more]}:
                    return txt
                case _ if hasattr(item, "text") and isinstance(getattr(item, "text"), str):
                    return getattr(item, "text")
                case _:
                    return ""

        batch = raw.get("batch")
        answers = [coerce(it).strip() for it in batch]
        return {"answers": answers, "confidence": 0.85, "structured_data": {"batch": batch}}

    return TransformSpec(name="batch_response", matcher=matcher, extractor=extractor, priority=95)
```

---

## 4. Minimal Projection (Fallback)

```python
class MinimalProjection:
    """Infallible fallback extractor.

    Guarantees:
    - Never raises exceptions
    - Always returns expected answer count
    - Handles any input shape
    """

    def extract(self, raw: Any, ctx: ExtractionContext) -> ExtractionResult:
        """Extract with progressive degradation."""
        text = self._to_text(raw)

        # Try JSON array
        if self._looks_like_json(text):
            arr = self._try_parse_json_array(text)
            if arr is not None:
                answers = self._normalize_and_pad(arr, ctx.expected_count)
                return ExtractionResult(
                    answers=answers,
                    method="minimal_json",
                    confidence=0.8
                )

        # Try numbered list (1. answer, 2. answer)
        if ctx.expected_count > 1:
            numbered = self._try_numbered_list(text)
            if numbered and len(numbered) >= ctx.expected_count * 0.5:
                answers = self._pad_to_count(numbered, ctx.expected_count)
                return ExtractionResult(
                    answers=answers,
                    method="minimal_numbered",
                    confidence=0.6
                )

        # Try newline splitting
        if ctx.expected_count > 1 and "\n" in text:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if lines:
                answers = self._pad_to_count(lines, ctx.expected_count)
                return ExtractionResult(
                    answers=answers,
                    method="minimal_newlines",
                    confidence=0.5
                )

        # Ultimate fallback: raw text
        if ctx.expected_count == 1:
            answers = [text]
        else:
            # Pad with empty strings for batch
            answers = [text] + [""] * (ctx.expected_count - 1)

        return ExtractionResult(
            answers=answers,
            method="minimal_text",
            confidence=0.3
        )

    def _to_text(self, raw: Any) -> str:
        """Convert any input to text safely."""
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            # Try common keys
            for key in ("text", "content", "answer", "response"):
                if key in raw:
                    return str(raw[key])
        if hasattr(raw, "text"):
            return str(raw.text)
        return str(raw)

    def _normalize_and_pad(self, items: list, count: int) -> list[str]:
        """Normalize items and pad to expected count."""
        # Handle nulls and nested lists
        if items and isinstance(items[0], list):
            items = items[0]  # Shallow flatten

        normalized = ["" if x is None else str(x) for x in items]

        # Pad or truncate
        if len(normalized) >= count:
            return normalized[:count]
        return normalized + [""] * (count - len(normalized))
```

---

## 5. Main Result Builder

```python
@dataclass(frozen=True)
class ResultBuilder:
    """Transform chain handler for result extraction.

    Properties:
    - Deterministic: Same input → same output
    - Infallible: Always returns Success
    - Observable: Rich diagnostics when enabled
    - Extensible: Add transforms without modification
    """

    transforms: tuple[TransformSpec, ...] = field(
        default_factory=lambda: tuple(default_transforms())
    )
    enable_diagnostics: bool = False
    max_text_size: int = 1_000_000  # 1MB limit

    async def handle(
        self,
        command: FinalizedCommand
    ) -> Result[dict[str, Any], Never]:
        """Extract results from finalized command.

        Guarantees:
        - Always returns Success
        - O(n) with response size
        - No I/O operations
        - Deterministic extraction
        """
        raw = command.raw_api_response
        ctx = self._build_context(command)
        diagnostics = ExtractionDiagnostics() if self.enable_diagnostics else None

        # Truncate large responses
        if isinstance(raw, (str, dict)) and self._is_oversized(raw):
            raw = self._truncate(raw)
            if diagnostics:
                diagnostics.flags.add("truncated_input")

        # Try transforms in priority order (with stable name sort for ties)
        result = None
        for transform in sorted(
            self.transforms,
            key=lambda t: (-t.priority, t.name)
        ):
            if diagnostics:
                diagnostics.attempted_transforms.append(transform.name)

            if transform.matcher(raw):
                try:
                    extracted = transform.extractor(raw, ctx.config)
                    result = self._build_from_extraction(
                        extracted,
                        command,
                        transform.name
                    )
                    if diagnostics:
                        diagnostics.successful_transform = transform.name
                    break
                except Exception as e:
                    if diagnostics:
                        diagnostics.transform_errors[transform.name] = str(e)
                    continue

        # Fallback if no transform succeeded
        if result is None:
            fallback = MinimalProjection().extract(raw, ctx)
            result = self._build_from_extraction(
                {"answers": fallback.answers, "confidence": fallback.confidence},
                command,
                fallback.method
            )
            if diagnostics:
                diagnostics.successful_transform = fallback.method

        # Schema validation (record-only)
        violations = self._validate_schema(result, ctx)

        # Contract validation (record-only)
        # Note: Additionally, record a pre-normalization mismatch warning to reflect
        # raw extraction fidelity before padding/truncation.
        contract = ExtractionContract(answer_count=ctx.expected_count)
        violations.extend(contract.validate(result))

        # Attach diagnostics
        if diagnostics:
            diagnostics.contract_violations = violations
            diagnostics.expected_answer_count = ctx.expected_count
            diagnostics.original_answer_count = original_answer_count
            result["diagnostics"] = asdict(diagnostics)
        elif violations:
            result["validation_warnings"] = tuple(v.message for v in violations)

        return Success(result)

    def _validate_schema(
        self,
        result: dict,
        ctx: ExtractionContext
    ) -> list[Violation]:
        """Single-pass schema validation (record-only)."""
        if ctx.schema is None:
            return []

        violations = []
        try:
            # Attempt Pydantic validation
            if hasattr(ctx.schema, "model_validate"):
                payload = result.get("structured_data") or {"answers": result["answers"]}
                ctx.schema.model_validate(payload)
            else:
                violations.append(
                    Violation("Schema not Pydantic v2 model", "info")
                )
        except Exception as e:
            violations.append(
                Violation(f"Schema validation: {e}", "warning")
            )

        return violations
```

---

## 6. Testing Strategy

### Unit Tests

```python
def test_transform_priority_ordering():
    """Verify transforms execute in priority order."""
    t1 = TransformSpec("low", lambda x: True, lambda x, c: {"answers": ["low"]}, 10)
    t2 = TransformSpec("high", lambda x: True, lambda x, c: {"answers": ["high"]}, 90)

    builder = ResultBuilder(transforms=(t1, t2))
    result = await builder.handle(mock_command({"text": "test"}))

    assert result.value["answers"] == ["high"]
    assert result.value["extraction_method"] == "high"

def test_deterministic_tiebreaker():
    """Equal priority sorts by name."""
    t1 = TransformSpec("zebra", lambda x: True, lambda x, c: {"answers": ["z"]}, 50)
    t2 = TransformSpec("alpha", lambda x: True, lambda x, c: {"answers": ["a"]}, 50)

    builder = ResultBuilder(transforms=(t1, t2))
    result = await builder.handle(mock_command({"text": "test"}))

    assert result.value["extraction_method"] == "alpha"  # Name sort

def test_minimal_fallback_never_fails():
    """Fallback handles any input."""
    inputs = [None, "", {}, [], {"random": "data"}, Exception("test")]

    for raw in inputs:
        projection = MinimalProjection()
        result = projection.extract(raw, ExtractionContext(expected_count=3))
        assert len(result.answers) == 3  # Always returns expected count

def test_schema_violations_dont_fail():
    """Schema violations recorded but don't fail extraction."""
    schema = MockSchema(validates=False)
    builder = ResultBuilder(enable_diagnostics=True)

    result = await builder.handle(mock_command_with_schema(schema))
    assert result.status == "ok"
    assert "validation_warnings" in result.value or "diagnostics" in result.value
```

### Property Tests

```python
from hypothesis import given, strategies as st

@given(
    text=st.text(),
    expected=st.integers(min_value=1, max_value=100)
)
def test_always_returns_expected_count(text, expected):
    """Always returns exactly the expected number of answers."""
    projection = MinimalProjection()
    result = projection.extract({"text": text}, ExtractionContext(expected))
    assert len(result.answers) == expected

@given(raw=st.dictionaries(st.text(), st.text()))
def test_never_raises_exceptions(raw):
    """Result builder never raises exceptions."""
    builder = ResultBuilder()
    command = mock_command(raw)
    result = await builder.handle(command)
    assert isinstance(result, Success)
```

### Contract Tests

```python
def test_pipeline_contract():
    """Maintains pipeline handler contract."""
    builder = ResultBuilder()

    # Accepts FinalizedCommand
    command = FinalizedCommand(planned=..., raw_api_response=...)

    # Returns Result[dict, Never]
    result = await builder.handle(command)

    # Never fails
    assert isinstance(result, Success)

    # Returns stable envelope
    assert "status" in result.value
    assert "answers" in result.value
    assert isinstance(result.value["answers"], list)
```

---

## 7. Performance Characteristics

### Time Complexity

- **Transform matching**: O(t) where t = number of transforms (pre-sorted on initialization)
- **Extraction**: O(n) where n = response size
- **Padding**: O(a) where a = answer count
- **Overall**: O(t + n + a), typically O(n) dominated

### Space Complexity

- **Response truncation**: Capped at max_text_size (1MB default). Oversize detection for dicts uses a heuristic based on stringified size; only string fields are truncated. This may flag oversized dicts even when truncation does not reduce size; acceptable tradeoff for simplicity.
- **No response copying**: Operates on references
- **Result envelope**: O(a) for answers array

### Benchmarks

```python
# Expected performance targets
# 10KB response: < 1ms
# 100KB response: < 5ms
# 1MB response: < 20ms
# 10MB response (truncated): < 25ms
```

---

## 8. Extension Guide

### Adding Custom Transforms

```python
def my_custom_transform() -> TransformSpec:
    """Example custom transform for specific format."""

    def matcher(raw: Any) -> bool:
        # Check if this format applies
        return "my_marker" in str(raw)

    def extractor(raw: Any, ctx: dict) -> dict:
        # Extract answers
        return {
            "answers": ["extracted", "values"],
            "confidence": 0.85,
            "structured_data": None
        }

    return TransformSpec(
        name="my_custom",
        matcher=matcher,
        extractor=extractor,
        priority=100  # Higher than built-ins
    )

# Usage
builder = ResultBuilder(
    transforms=tuple(default_transforms()) + (my_custom_transform(),)
)
```

### Custom Contracts

```python
@dataclass(frozen=True)
class StrictContract(ExtractionContract):
    """Custom contract with additional validations."""

    must_start_with: str = ""

    def validate(self, result: dict[str, Any]) -> list[Violation]:
        violations = super().validate(result)

        for i, answer in enumerate(result.get("answers", [])):
            if not answer.startswith(self.must_start_with):
                violations.append(
                    Violation(
                        f"Answer {i} doesn't start with '{self.must_start_with}'",
                        "warning"
                    )
                )

        return violations
```

---

## 9. Migration from Legacy

### Before (response/processor.py)

```python
# Multiple extraction paths
if response.parsed:
    # Path A: structured
elif "```json" in response.text:
    # Path B: markdown JSON
else:
    # Path C: fallback
```

### After (pipeline/result_builder.py)

```python
# Single, deterministic flow
for transform in sorted_transforms:
    if transform.matcher(raw):
        try:
            return transform.extractor(raw, ctx)
        except:
            continue
return fallback.extract(raw, ctx)
```

---

## 10. Design Rationale

### Why Two Tiers?

- **Tier 1** handles known formats optimally
- **Tier 2** guarantees success for unknown formats
- Clear separation without complex ranking

### Why Explicit Priorities?

- Deterministic ordering
- No hidden scoring logic
- Easy to debug and reason about

### Why Record-Only Validation?

- 100% extraction success rate
- Observability without brittleness
- Schema changes don't break extraction

### Why Pure Functions?

- Trivial to test
- No hidden state
- Perfectly composable

---

## Related Documents

- [Concept – Result Building](../concepts/result-building.md)
- [ADR-0005 – Two-Tier Result Builder](../decisions/ADR-0005-result-builder.md)
- [How-to – Custom Transforms](../../how-to/custom-transforms.md)
- [Architecture Rubric](../architecture-rubric.md)
!!! note "Draft – pending revision"
    This specification will be reworked for clarity and efficacy. Included in nav for discoverability; content to be reviewed before release.

Last reviewed: 2025-09
