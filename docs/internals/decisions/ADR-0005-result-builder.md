# ADR-0005: Two-Tier Transform Chain for Result Building

**Date:** 2025-01-11
**Status:** Accepted
**Tags:** result-builder, extraction, transforms, pipeline
**Audience:** Contributors and extension authors
**Impacted Modules/APIs:** `ResultBuilder`, transform chain specs, result envelope shape

---

## Context

The Result Builder must transform raw API responses into stable, predictable results for both single and batch requests. Model outputs are fundamentally unpredictable despite prompt engineering, varying between JSON, markdown, natural language, and mixed formats.

Previous approaches in `response/processor.py` had:

- **Multiple extraction paths** with complex branching logic
- **Brittle parsing** that failed on format variations
- **Inconsistent error handling** between single and batch modes
- **Poor observability** into extraction decisions
- **Tight coupling** to specific response formats

Requirements for the new design:

- Deterministic question→answer mapping
- Never fail extraction (100% success rate)
- Provider-neutral implementation
- O(n) performance with batch size
- Audit-grade observability
- User-extensible without code modification

---

## Decision

Adopt a **Two-Tier Transform Chain** with **record-only validation**:

### Tier 1: Transform Chain

- Ordered list of pure extraction transforms
- Each transform has explicit priority
- First successful match wins
- Transforms are pure functions: `(raw, context) → result`

### Tier 2: Minimal Projection

- Infallible fallback extractor
- Progressive degradation through extraction attempts
- Guarantees answer count through deterministic padding

### Key Elements

1. **No Failure Mode** - Extraction always succeeds, worst case returns raw text
2. **Record-Only Validation** - Schema violations logged but don't fail extraction
3. **Explicit Priorities** - No hidden scoring or confidence ranking
4. **Pure Functions** - All transforms are stateless and deterministic
5. **Single Result Shape** - Same envelope for single and batch requests

### Implementation

```python
@dataclass(frozen=True)
class TransformSpec:
    name: str
    matcher: Callable[[Any], bool]  # Predicate
    extractor: Callable[[Any, dict], dict]  # Pure transform
    priority: int = 0  # Higher runs first

@dataclass(frozen=True)
class ResultBuilder:
    transforms: tuple[TransformSpec, ...]
    enable_diagnostics: bool = False

    async def handle(self, command: FinalizedCommand) -> Result[dict]:
        # Try transforms by priority
        for t in sorted(self.transforms, key=lambda t: (-t.priority, t.name)):
            if t.matcher(raw):
                try:
                    result = t.extractor(raw, context)
                    return Success(self._build_envelope(result))
                except:
                    continue  # Try next

        # Infallible fallback
        fallback = MinimalProjection().extract(raw, context)
        return Success(self._build_envelope(fallback))
```

---

## Consequences

### Positive

- **100% extraction success rate** - Fallback guarantees results
- **Fully deterministic** - Same input always produces same output
- **Trivial to test** - Pure functions without I/O
- **User extensible** - Add transforms without forking
- **Rich observability** - Complete diagnostic trail
- **O(n) performance** - Single pass, early exit

### Negative

- **No adaptation** - Cannot learn from patterns
- **Fixed priorities** - Must manually tune transform order
- **Limited intelligence** - No confidence-based selection

### Neutral

- Extraction quality depends on transform coverage
- Diagnostics add slight overhead when enabled
- Schema validation is informational only

---

## Alternatives Considered

### Alternative 1: Extraction Lenses with Verification

Complex composition with self-verification and learning.

- ❌ Too much complexity (lenses, verification, learning)
- ❌ Non-deterministic confidence scoring
- ❌ Harder to test and reason about

### Alternative 2: Schema-First Reducer

Everything treated as structured with schema wrapping.

- ❌ Heavy Pydantic dependency at boundary
- ❌ Poor for ad-hoc text extraction
- ❌ Adds unnecessary abstraction

### Alternative 3: Provider-Specific Adapters

Each provider has dedicated extraction logic.

- ❌ Duplication across providers
- ❌ Tight coupling to response formats
- ❌ Harder to maintain consistency

---

## Migration Path

### Phase 1: Consolidate Current (Day 1)

- Unify existing extraction paths
- Maintain current result shape
- Keep JSON-first behavior

### Phase 2: Transform Chain (Day 2)

- Extract logic into transforms
- Add minimal projection fallback
- Maintain backward compatibility

### Phase 3: Schema Wall (Day 3)

- Add validation pass
- Record violations in diagnostics
- Record a pre-normalization answer-count mismatch warning (observability)
- Never fail on validation

### Phase 4: Diagnostics (Day 4)

- Add extraction diagnostics
- Surface attempted transforms
- Include timing and violations
- Record pre-normalization answer-count mismatch separately from normalized contract

### Phase 5: User Transforms (Day 5)

- Document transform interface
- Enable user-provided transforms
- Publish transform examples

---

## Validation Criteria

- All existing extraction tests pass
- 100% extraction success rate on test corpus
- Deterministic results for same input
- O(n) performance maintained
- Diagnostics correctly track attempts
- User transforms integrate cleanly

---

## References

- [Concept – Result Building](../concepts/result-building.md)
- [Deep Dive – Result Builder Spec](../deep-dives/result-builder-spec.md)
- [Architecture Rubric](../architecture-rubric.md)
- [Command Pipeline](./ADR-0001-command-pipeline.md)
