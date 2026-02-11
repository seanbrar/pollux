# Sources and Patterns

This page covers how to create sources, choose between `run()` and
`run_many()`, and interpret the result envelope.

## Source Constructors

| Constructor | Input | Notes |
|---|---|---|
| `Source.from_text(text)` | Plain string | Identifier defaults to first 50 chars |
| `Source.from_file(path)` | Local file path | Supports PDF, images, video, audio, text |
| `Source.from_youtube(url)` | YouTube URL | Gemini-native; limited on OpenAI in v1.0 |
| `Source.from_arxiv(ref)` | arXiv ID or URL | Downloads the PDF automatically |
| `Source.from_uri(uri, mime_type=...)` | Remote URI | Generic fallback for any hosted content |

Examples:

```python
from pollux import Source

text    = Source.from_text("Caching reduces repeated token cost.")
paper   = Source.from_file("paper.pdf")
video   = Source.from_youtube("https://youtube.com/watch?v=dQw4w9WgXcQ")
arxiv   = Source.from_arxiv("2301.00001")
remote  = Source.from_uri("https://example.com/data.csv", mime_type="text/csv")
```

## Single Prompt: `run()`

Use `run()` when you have one prompt and at most one source.

```python
import asyncio
from pollux import Config, Source, run

async def main() -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")
    result = await run(
        "What are the main conclusions?",
        source=Source.from_file("paper.pdf"),
        config=config,
    )
    print(result["status"])   # "ok"
    print(result["answers"][0])

asyncio.run(main())
```

Output:

```
ok
The paper concludes that context caching reduces repeated token cost by up to
90% for fan-out workloads, with diminishing returns below 3 prompts per source.
```

## Multiple Prompts: `run_many()`

Use `run_many()` when prompts or sources are plural. It handles upload reuse,
concurrency, and cache identity automatically.

```python
import asyncio
from pollux import Config, Source, run_many

async def main() -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")
    sources = [
        Source.from_file("paper1.pdf"),
        Source.from_file("paper2.pdf"),
    ]
    prompts = [
        "Summarize the main argument.",
        "List key findings.",
    ]

    envelope = await run_many(prompts, sources=sources, config=config)
    print(envelope["status"])
    for i, answer in enumerate(envelope["answers"], 1):
        print(f"Q{i}: {answer[:80]}...")

asyncio.run(main())
```

Output:

```
ok
Q1: Paper 1 argues that multimodal orchestration layers reduce boilerplate by...
Q2: Key findings: (1) fan-out caching saves 85-92% of input tokens; (2) broad...
```

## Structured Output

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

## Choosing `run()` vs `run_many()`

| Situation | Use | Why |
|---|---|---|
| One question, optional source | `run()` | Smallest surface area |
| Multiple questions on shared source(s) | `run_many()` | Fan-out efficiency |
| Same question across many sources | `run_many()` | Fan-in analysis |
| Many questions across many sources | `run_many()` | Broadcast pattern |

Rule of thumb: if prompts or sources are plural, use `run_many()`.

`run()` is a convenience wrapper that delegates to `run_many()` with a single
prompt.

## ResultEnvelope Reference

Every call returns a `ResultEnvelope` dict. Here are all fields:

| Field | Type | Always present | Description |
|---|---|---|---|
| `status` | `"ok" \| "partial" \| "error"` | Yes | `ok` = all answers populated; `partial` = some empty; `error` = all empty |
| `answers` | `list[str]` | Yes | One string per prompt |
| `structured` | `list[Any]` | Only with `response_schema` | Parsed objects matching your schema |
| `reasoning` | `list[str \| None]` | No | Provider reasoning traces (when available) |
| `confidence` | `float` | Yes | `0.9` for ok, `0.5` otherwise |
| `extraction_method` | `str` | Yes | Always `"text"` in v1.0 |
| `usage` | `dict[str, int]` | Yes | Token counts (`prompt_tokens`, `completion_tokens`, `total_tokens`) |
| `metrics` | `dict[str, Any]` | Yes | `duration_s`, `n_calls`, `cache_used` |

Example of a complete envelope:

```python
{
    "status": "ok",
    "answers": ["The paper concludes that..."],
    "confidence": 0.9,
    "extraction_method": "text",
    "usage": {"prompt_tokens": 1250, "completion_tokens": 89, "total_tokens": 1339},
    "metrics": {"duration_s": 1.42, "n_calls": 1, "cache_used": False},
}
```

## v1.0 Notes

- Conversation continuity (`history`, `continue_from`) is reserved and
  disabled in v1.0.
- `delivery_mode="deferred"` is reserved and disabled in v1.0.
- Provider feature support varies. See
  [Provider Capabilities](reference/provider-capabilities.md).
