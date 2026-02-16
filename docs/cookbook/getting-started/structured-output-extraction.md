# Structured Output Extraction

Use a Pydantic schema to get typed, validated output instead of parsing JSON
by hand.

## Defining the Schema

The recipe uses a `DocumentSummary` schema with `bullets` and `risks` fields.
In your own code, define whatever structure fits your extraction task:

```python
from pydantic import BaseModel

class DocumentSummary(BaseModel):
    bullets: list[str]
    risks: list[str]
```

Pollux passes this schema to the provider via `Options(response_schema=...)`.
The provider returns structured JSON; Pollux validates and parses it into your
model.

## Run It

Mock mode (validates flow and schema shape):

```bash
python -m cookbook getting-started/structured-output-extraction \
  --input cookbook/data/demo/text-medium/input.txt --mock
```

Real API (returns actual structured data):

```bash
python -m cookbook getting-started/structured-output-extraction \
  --input path/to/file.pdf --no-mock --provider openai --model gpt-5-nano
```

## What You'll See

In `--no-mock` mode:

```
Status: ok
Structured output:
  bullets (3): ["Context caching reduces cost by 90%", ...]
  risks (2): ["Provider lock-in for caching features", ...]
Raw answer (excerpt): The document describes three key findings...
```

The `structured` field in the envelope contains a parsed `DocumentSummary`
object. The raw text answer is still available in `answers` as a fallback.

In `--mock` mode, you'll see a schema preview instead — the mock provider
doesn't emit real structured payloads.

## Tuning

- Tighten the schema (required fields, enums, constraints) as you learn
  edge cases from real output.
- Make the prompt demand specificity: "source-labeled bullets with concrete
  facts" works better than "summarize".
- If `structured` is missing in real mode, the provider/model may not
  support structured outputs — check
  [Provider Capabilities](../../reference/provider-capabilities.md).

## Next Steps

Pair with [Run vs RunMany](../optimization/run-vs-run-many.md) for
multi-question extraction, or add validation pipelines downstream by
writing `structured` to JSONL.
