# Comparative Analysis

Generate structured similarities/differences across two sources.

## At a glance

- **Best for:** review workflows needing explicit comparisons.
- **Input:** two files (or fallback directory auto-pick).
- **Output:** parsed JSON summary with key comparison buckets.

## Command

```bash
python -m cookbook research-workflows/comparative-analysis -- \
  file_a.pdf file_b.pdf
```

Fallback pair from directory:

```bash
python -m cookbook research-workflows/comparative-analysis -- \
  --input cookbook/data/demo/text-medium
```

## Expected signal

- Parsed output includes `similarities`, `differences`, `strengths`, `weaknesses`.
- Summary shows useful counts and an actionable first difference.

## Interpret the result

- If parsing fails, tighten prompt constraints around strict JSON.
- If differences are shallow, sources may be too similar or too short.
- Stable structure is more important than stylistic phrasing.

## Common pitfalls

- Letting prose slip into response instead of JSON.
- Comparing mismatched source types with low shared context.
- Modifying key names in prompt/output contract.

## Try next

- Validate output with a strict Pydantic schema.
- Add weighted scoring for disagreement severity.
