# How-to: Add Custom Extraction Transforms

This guide shows how to add a custom, pure extraction transform to `ResultBuilder`’s Tier 1 Transform Chain.

- Define a `TransformSpec` with a matcher and extractor
- Provide it to `ResultBuilder` (optionally alongside the defaults)
- Optionally enable diagnostics to observe selection

Keep transforms simple, deterministic, and IO-free.

## Prerequisites

- Working knowledge of Python
- Familiarity with `ResultBuilder` and `TransformSpec` APIs

## 1) Define a transform

```python
from typing import Any
from pollux.pipeline.results.extraction import TransformSpec

# Match a specific structure
def matcher(raw: Any) -> bool:
    return isinstance(raw, dict) and raw.get("my_marker") is True

# Extract answers deterministically (no IO, no side effects)
def extractor(raw: Any, _ctx: dict[str, Any]) -> dict[str, Any]:
    value = str(raw.get("value", ""))
    return {"answers": [value], "confidence": 0.85}

my_transform = TransformSpec(
    name="my_custom",
    matcher=matcher,
    extractor=extractor,
    priority=100,  # Higher priority tried first; ties break by name
)
```

Optional: use a small factory for per-transform configuration.

```python
def make_my_transform(prefix: str = "") -> TransformSpec:
    def matcher(raw: Any) -> bool:
        return isinstance(raw, dict) and raw.get("my_marker") is True

    def extractor(raw: Any, _ctx: dict[str, Any]) -> dict[str, Any]:
        return {"answers": [prefix + str(raw.get("value", ""))], "confidence": 0.85}

    return TransformSpec(name="my_custom", matcher=matcher, extractor=extractor, priority=100)
```

## 2) Use it with the Result Builder

```python
from pollux.pipeline.result_builder import ResultBuilder

# Supply only your transform
builder = ResultBuilder(transforms=(my_transform,))
result = await builder.handle(finalized_command)
answers = result.value["answers"]
```

Combine with the defaults when desired (priority controls order):

```python
from pollux.pipeline.results.transforms import default_transforms

builder = ResultBuilder(transforms=(make_my_transform(prefix="[X] "), *default_transforms()))
```

## 3) Optional: Observe selection with diagnostics

```python
builder = ResultBuilder(transforms=(my_transform,), enable_diagnostics=True)
result = await builder.handle(finalized_command)
print(result.value["diagnostics"])  # attempted_transforms, successful_transform, timing, etc.
```

## Notes and guidance

- Transforms must be pure (no IO, no global state); identical input yields identical output.
- Extractors must return `answers` as a `list[str]` (tuples or scalars are not accepted).
- Prefer higher priority for more specific transforms; general transforms should use lower priority.
- For configuration, prefer a transform-factory pattern (as shown above). `ExtractionContext.config` exists but is not currently injected by `ResultBuilder`.

## Troubleshooting

- Transform didn’t run? Check `diagnostics["attempted_transforms"]` and your matcher predicate.
- Got more/fewer answers than expected? The builder pads/truncates for consistency and records a pre-normalization mismatch warning in diagnostics.

## Related

- [Explanation: Result Building](../explanation/concepts/result-building.md)
- [Deep Dive: Result Builder Spec](../explanation/deep-dives/result-builder-spec.md)
- [ADR-0005: Two-Tier Result Builder](../explanation/decisions/ADR-0005-result-builder.md)
