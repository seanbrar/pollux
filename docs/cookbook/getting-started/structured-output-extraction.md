# Structured Output Extraction

Use a schema to get typed, validated output instead of parsing JSON by hand.

## At a glance

- **Best for:** pipelines that need validated fields (ETL, evaluation, indexing).
- **Input:** one local file (`pdf/txt/md`).
- **Output:** a structured payload in `envelope["structured"]` plus the raw answer text.

## Before you run

- Start in `--mock` to validate the flow and schema shape.
- Switch to `--no-mock` once your schema is stable, and track validation failures.

## Command

```bash
python -m cookbook getting-started/structured-output-extraction \
  --input cookbook/data/demo/text-medium/input.txt --mock
```

Real API mode:

```bash
python -m cookbook getting-started/structured-output-extraction \
  --input path/to/file.pdf --no-mock --provider openai --model gpt-4.1-mini
```

## What to look for

- `Structured output` prints counts for `bullets` and `risks`.
- The raw answer excerpt should still be readable; structured output is the “contract”.
- In real mode, schema failures should be rare once prompts are stable.

## Tuning levers

- Tighten the schema (required fields, enums, min/max lengths) as you learn edge cases.
- Make the prompt demand specificity (source-labeled bullets, concrete facts).

## Failure modes

- If `structured` is missing, the provider/model likely doesn’t support structured outputs.
- If fields are empty, your prompt may be too vague or your schema too strict.
- Schema drift: changes to prompts/sources can silently change field distributions.

## Extend this recipe

- Add downstream validation and persistence (write `structured` to JSONL).
- Pair with [Run vs RunMany](../optimization/run-vs-run-many.md) for multi-question extraction.
- For multimodal baselines, start with [Extract Media Insights](extract-media-insights.md).
