# Comparative Analysis

Generate structured differences and similarities between two sources using
fan-in — many sources fed into a single comparison prompt.

## Run It

Explicit file paths:

```bash
python -m cookbook research-workflows/comparative-analysis \
  --input cookbook/data/demo/text-medium/input.txt \
  cookbook/data/demo/text-medium/compare.txt --mock
```

Fallback directory mode (picks the first two files):

```bash
python -m cookbook research-workflows/comparative-analysis \
  --input cookbook/data/demo/text-medium --mock
```

## What You'll See

```
Status: ok
Comparison (JSON):
{
  "similarities": ["Both discuss context caching", "Both use async pipelines"],
  "differences": ["Paper A focuses on fan-out; Paper B emphasizes fan-in"],
  "strengths": {"paper_a": "Detailed benchmarks", "paper_b": "Broader scope"},
  "weaknesses": {"paper_a": "Limited providers", "paper_b": "No cost analysis"}
}

Key difference: Paper A focuses on fan-out; Paper B emphasizes fan-in
```

The parsed output includes similarities, differences, strengths, and
weaknesses. The count summary helps detect under-specified responses.

## Tuning

- Choose sources that are comparable in scope for meaningful output.
- Constrain comparison dimensions in the prompt (method, evidence, risk, cost).
- If output isn't valid JSON, tighten schema language in the prompt.

## Next Steps

Add Pydantic validation for structured comparison output (see
[Contributing](../../contributing.md) for recipe authoring guidance). Pair
with [Multi-Video Synthesis](multi-video-synthesis.md) for multimodal
comparisons.
