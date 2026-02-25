# Analyzing Collections with Source Patterns

You have a directory of files and want to run the same analysis across all of
them, or synthesize across multiple sources, or both. Pollux handles each
file's API calls; your code owns iteration, concurrency, and aggregation.

Source patterns describe the relationship between sources and prompts:

```mermaid
graph LR
    subgraph Fan-out
        S1[Source] --> P1a[Prompt 1]
        S1 --> P2a[Prompt 2]
    end
    subgraph Fan-in
        S2a[Source 1] --> Pa[Prompt]
        S2b[Source 2] --> Pa
    end
    subgraph Broadcast
        S3a[Source 1] --> P3a[Prompt 1]
        S3a --> P3b[Prompt 2]
        S3b[Source 2] --> P3a
        S3b --> P3b
    end
```

- **Fan-out** — one source, many prompts. Upload an artifact once, ask
  multiple questions. Context caching pays off here.
- **Fan-in** — many sources, one prompt. Synthesize across artifacts with a
  single question. Useful for comparisons and cross-document analysis.
- **Broadcast** — many sources × many prompts. Apply the same analysis
  template across a collection. Consistent prompts make output comparison
  straightforward.

!!! info "Boundary"
    **Pollux owns:** source upload, context caching, concurrent API calls
    within a single `run_many()`, retries, and result normalization.

    **You own:** file discovery, the outer iteration loop, cross-file
    concurrency, result aggregation, and partial-failure decisions.

## Processing a Collection

The pattern is a two-level loop:

- **Outer loop (your code):** iterates over files, controls concurrency
  across files, and collects results.
- **Inner call (Pollux):** `run()` or `run_many()` handles one file's
  prompts, uploads, caching, and concurrent API calls.

Process all PDFs in a directory, ask two questions about each, and collect
results into a summary dictionary:

```python
import asyncio
from pathlib import Path

from pollux import Config, Options, Source, run_many

config = Config(provider="gemini", model="gemini-2.5-flash-lite")

PROMPTS = [
    "What is the main argument of this document?",
    "List the key findings as bullet points.",
]


async def analyze_file(path: Path) -> dict:
    """Analyze a single file with multiple prompts."""
    source = Source.from_file(str(path))
    result = await run_many(
        PROMPTS,
        sources=(source,),
        config=config,
    )
    return {
        "file": path.name,
        "status": result["status"],
        "main_argument": result["answers"][0],
        "key_findings": result["answers"][1],
        "tokens": result["usage"]["total_tokens"],
    }


async def process_directory(directory: str) -> list[dict]:
    """Process all PDFs in a directory and return summaries."""
    pdf_dir = Path(directory)
    pdf_files = sorted(pdf_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDFs found in {directory}")
        return []

    results = []
    for path in pdf_files:
        try:
            summary = await analyze_file(path)
            results.append(summary)
            print(f"  {path.name}: {summary['status']} ({summary['tokens']} tokens)")
        except Exception as exc:
            print(f"  {path.name}: FAILED — {exc}")
            results.append({"file": path.name, "status": "error", "error": str(exc)})

    succeeded = sum(1 for r in results if r["status"] == "ok")
    print(f"\nProcessed {len(results)} files: {succeeded} ok, {len(results) - succeeded} failed")
    return results


asyncio.run(process_directory("./papers"))
```

## Fan-in: Synthesizing Across Sources

When you need to synthesize across files rather than analyze each one
independently, pass multiple sources to a single prompt:

```python
async def synthesize_collection(directory: str, question: str) -> str:
    """Ask one question about multiple sources together."""
    pdf_files = sorted(Path(directory).glob("*.pdf"))
    sources = tuple(Source.from_file(str(p)) for p in pdf_files)

    result = await run_many(
        question,
        sources=sources,
        config=config,
    )
    return result["answers"][0]
```

This sends all sources to the model in one call — useful for comparative
questions like "Which paper has the strongest methodology?" or "What themes
appear across all documents?"

For structured comparisons with typed output (similarities, differences,
strengths), combine fan-in with a `response_schema` — see
[Extracting Structured Data](structured-data.md).

## Concurrent File Processing

Process multiple files in parallel while limiting concurrency to avoid
overwhelming the API:

```python
CONCURRENCY = 3

async def process_directory_concurrent(directory: str) -> list[dict]:
    """Process files concurrently with bounded parallelism."""
    pdf_dir = Path(directory)
    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def bounded_analyze(path: Path) -> dict:
        async with semaphore:
            try:
                return await analyze_file(path)
            except Exception as exc:
                return {"file": path.name, "status": "error", "error": str(exc)}

    return await asyncio.gather(*(bounded_analyze(p) for p in pdf_files))
```

Pollux already limits concurrent API calls *within* each `run_many()` via
`Config.request_concurrency`. The semaphore here controls how many *files*
are processed simultaneously — a separate concern. Start conservative (2-4
concurrent files) and ramp up until reliability drops.

## Writing Results to JSONL

Stream results to a JSONL file for downstream processing:

```python
import json

async def process_to_jsonl(directory: str, output: str) -> None:
    """Process all PDFs and write results as JSONL."""
    pdf_files = sorted(Path(directory).glob("*.pdf"))

    with open(output, "w") as f:
        for path in pdf_files:
            try:
                summary = await analyze_file(path)
            except Exception as exc:
                summary = {"file": path.name, "status": "error", "error": str(exc)}
            f.write(json.dumps(summary) + "\n")

    print(f"Wrote {len(pdf_files)} results to {output}")
```

## What to Watch For

- **Fan-out per file vs fan-in across files.** The complete example uses
  fan-out (one file, many prompts). The fan-in variation reverses this.
  Choose based on whether your question is about individual files or the
  collection as a whole.
- **Semaphore vs `request_concurrency`.** Pollux's `request_concurrency`
  controls API calls within a single `run_many()`. Your semaphore controls
  how many files process simultaneously. Both matter for rate limits.
- **Partial failures are normal.** Large collections will have occasional
  failures — bad PDFs, rate limits that exhaust retries, timeouts. Design
  your aggregation to handle `status: "error"` entries. See
  [Handling Errors and Recovery](error-handling.md) for production patterns.
- **Memory with large collections.** Each `Source.from_file()` reads the
  file for hashing. For very large collections, process in batches rather
  than loading all sources at once.
- **Caching helps fan-out, not iteration.** `enable_caching=True` saves
  tokens when the *same source* is reused across multiple prompts. It does
  not help when each file is different — see
  [Reducing Costs with Context Caching](caching.md).
