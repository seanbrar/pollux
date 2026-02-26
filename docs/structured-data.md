<!-- Intent: Teach structured output extraction via response_schema. Cover
     Pydantic models, JSON schema dicts, nested models, and combining with
     reasoning. Do NOT cover tool calling, conversation history, or caching.
     Assumes the reader understands run() and ResultEnvelope from Sending
     Content. Register: guided applied. -->

# Extracting Structured Data

You want typed data from documents. Not free-form text, but validated objects
you can store, compare, and process programmatically. Pollux becomes a data
pipeline here.

At the LLM API level, structured output constrains the model's token
generation to conform to a JSON schema you provide. Instead of producing
arbitrary prose, the model fills in fields that match your schema's types and
required properties. The result is parseable data, not text that needs
regex extraction.

!!! info "Boundary"
    **Pollux owns:** translating your schema to the provider's structured
    output format, parsing the response into typed objects, and populating
    `result["structured"]`.

    **You own:** defining Pydantic models (or JSON schema dicts), building
    the extraction pipeline, validating domain constraints beyond what the
    schema expresses, and writing results to storage.

## The `response_schema` Option

Pass a Pydantic model (or JSON schema dict) via `Options(response_schema=...)`
to get typed, validated output in `envelope["structured"]`.

```python
import asyncio
from pydantic import BaseModel
from pollux import Config, Options, Source, run

class PaperSummary(BaseModel):
    title: str
    findings: list[str]

async def main() -> None:
    config = Config(provider="openai", model="gpt-5-nano")
    options = Options(response_schema=PaperSummary)
    result = await run(
        "Extract a structured summary.",
        source=Source.from_text("Title: Caching Study. Findings: tokens saved, latency reduced."),
        config=config,
        options=options,
    )
    summary = result["structured"][0]
    print(summary.title)       # "Caching Study"
    print(summary.findings)    # ["tokens saved", "latency reduced"]

asyncio.run(main())
```

When `response_schema` is set, the `structured` field contains one parsed
object per prompt. The raw text is still available in `answers`.

## Complete Extraction Pipeline

Let's build something real: extract metadata from research papers into a
typed catalog and write to JSONL. This is a common pattern for building
datasets from document collections.

```python
import asyncio
import json
from pathlib import Path

from pydantic import BaseModel

from pollux import Config, Options, Source, run


class PaperMetadata(BaseModel):
    title: str
    authors: list[str]
    year: int
    abstract_summary: str
    key_findings: list[str]
    methodology: str


config = Config(provider="gemini", model="gemini-2.5-flash-lite")
options = Options(response_schema=PaperMetadata)


async def extract_metadata(path: Path) -> PaperMetadata:
    """Extract structured metadata from a single paper."""
    result = await run(
        "Extract the paper metadata. Include all authors, the publication "
        "year, a one-sentence abstract summary, key findings, and the "
        "methodology used.",
        source=Source.from_file(str(path)),
        config=config,
        options=options,
    )
    return result["structured"][0]


async def build_catalog(directory: str, output: str) -> None:
    """Build a JSONL catalog from all PDFs in a directory."""
    pdf_files = sorted(Path(directory).glob("*.pdf"))

    with open(output, "w") as f:
        for path in pdf_files:
            try:
                metadata = await extract_metadata(path)
                f.write(metadata.model_dump_json() + "\n")
                print(f"  {path.name}: {metadata.title} ({metadata.year})")
            except Exception as exc:
                print(f"  {path.name}: FAILED — {exc}")

    print(f"\nWrote catalog to {output}")


asyncio.run(build_catalog("./papers", "catalog.jsonl"))
```

### Step-by-Step Walkthrough

1. **Define a Pydantic model.** `PaperMetadata` declares the exact fields
   and types you expect. The model constrains both the LLM's output format
   and your downstream code's type expectations.

2. **Pass the schema via `Options`.** `Options(response_schema=PaperMetadata)`
   tells Pollux to request structured output from the provider. Pollux
   handles the translation to provider-specific schema formats.

3. **Read from `result["structured"]`.** When `response_schema` is set,
   `result["structured"]` contains one parsed object per prompt. For
   `run()` (single prompt), access `result["structured"][0]`.

4. **Serialize to storage.** Pydantic models serialize cleanly to JSON via
   `model_dump_json()`. Write one object per line for JSONL, or use
   `model_dump()` for dicts.

5. **Handle failures per file.** Schema enforcement helps, but the model
   can still produce incomplete data or the API call can fail. Catch
   exceptions at the file level.

## JSON Schema Dicts for Dynamic Schemas

When your schema isn't known at import time (loaded from a config file,
built per-user), pass a JSON schema dict instead of a Pydantic model:

```python
schema = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "topics"],
}

options = Options(response_schema=schema)
result = await run(prompt, source=source, config=config, options=options)

# result["structured"][0] is a dict (no Pydantic model to parse into)
print(result["structured"][0]["title"])
```

## Nested Models

Pydantic models can nest arbitrarily. Use this for rich document structures:

```python
class Author(BaseModel):
    name: str
    affiliation: str | None = None

class Citation(BaseModel):
    title: str
    authors: list[str]
    year: int

class DetailedPaper(BaseModel):
    title: str
    authors: list[Author]
    abstract: str
    sections: list[str]
    citations: list[Citation]
```

Pollux flattens the nested model into a JSON schema that the provider
enforces. The response is parsed back into the full nested structure.

## Structured Output with Reasoning

Combine `response_schema` with `reasoning_effort` to get both structured
data and the model's reasoning trace:

```python
options = Options(
    response_schema=PaperMetadata,
    reasoning_effort="high",
)

result = await run(prompt, source=source, config=config, options=options)

metadata = result["structured"][0]       # Typed extraction
if "reasoning" in result and result["reasoning"][0]:
    print("Reasoning:", result["reasoning"][0][:200])  # Model's thought process
```

This is useful when you need to audit *why* the model extracted specific
values, for example when the methodology classification drives downstream
decisions.

## What to Watch For

- **Schema complexity affects reliability.** Flat schemas with descriptive
  field names work best. Deeply nested schemas with many optional fields
  produce inconsistent results. Simplify where you can.
- **Raw text is always available.** Even with `response_schema`, the raw
  model response is in `result["answers"]`. Useful for debugging when the
  structured output doesn't match expectations.
- **Both providers support structured output.** Gemini and OpenAI both
  support `response_schema`. See
  [Provider Capabilities](reference/provider-capabilities.md) for details.
- **Pydantic v2 is required.** Pollux uses `model_json_schema()` for schema
  generation. Pydantic v2 is a dependency of Pollux.
- **Domain validation is yours.** The schema enforces *shape* (types, required
  fields). Domain rules like "year must be between 1900 and 2026" belong in
  your code after extraction.
- **Tighten schemas iteratively.** Start with required fields and add
  constraints (enums, length limits) as you learn edge cases from real
  output. Make the prompt demand specificity: "source-labeled bullets with
  concrete facts" beats "summarize".

---

To add tool calling and multi-turn reasoning on top of structured extraction,
see [Building an Agent Loop](agent-loop.md). To
reduce token costs when running structured extraction across many prompts on
the same sources, see [Reducing Costs with Context Caching](caching.md).
