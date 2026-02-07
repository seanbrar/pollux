# Comparative Analysis

Generate structured differences and similarities between two sources.

## At a glance

- **Best for:** side-by-side research review and decision support.
- **Input:** two file paths (or fallback directory with at least two files).
- **Output:** parsed JSON comparison summary and key difference signal.

## Before you run

- Choose sources that are comparable in scope.
- Prefer explicit file paths for reproducible comparisons.

## Command

```bash
python -m cookbook research-workflows/comparative-analysis -- \
  cookbook/data/demo/text-medium/input.txt \
  cookbook/data/demo/text-medium/compare.txt --mock
```

Fallback directory mode:

```bash
python -m cookbook research-workflows/comparative-analysis -- \
  --input cookbook/data/demo/text-medium --mock
```

## What to look for

- Parsed output should include similarities, differences, strengths, weaknesses.
- Count summary helps detect under-specified responses quickly.
- First key difference should be concrete and decision-relevant.

## Tuning levers

- Tighten JSON schema language in prompt if parsing fails.
- Constrain comparison dimensions (method, evidence, risk, cost).

## Failure modes

- Non-JSON output indicates prompt or model adherence issues.
- Weak differences often mean sources are too similar or too broad.
- Missing files in fallback mode -> ensure at least two candidates.

## Extend this recipe

- Add Pydantic validation from [Custom Schema Template](../templates.md).
- Pair with [Multi-Video Synthesis](multi-video-synthesis.md) for multimodal comparisons.

