# Sending Content to Models

This page covers how to create sources, choose between `run()` and
`run_many()`, and interpret the result envelope.

!!! info "Boundary"
    **Pollux owns:** uploading and caching source content, attaching it to
    provider API calls, running prompts concurrently, and normalizing
    responses into a stable `ResultEnvelope`.

    **You own:** choosing what to analyze, writing prompts, and processing
    the returned answers.

## Source Constructors

| Constructor | Input | Notes |
|---|---|---|
| `Source.from_text(text)` | Plain string | Identifier defaults to first 50 chars |
| `Source.from_file(path)` | Local file path | Supports PDF, images, video, audio, text |
| `Source.from_youtube(url)` | YouTube URL | URL reference (no download); Gemini-native, limited on OpenAI in v1.0 |
| `Source.from_arxiv(ref)` | arXiv ID or URL | Normalizes to canonical PDF URL (no download at construction time) |
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

Pollux accepts PDFs, images, video, audio, and text files through the same
interface. The source type is detected from the file extension or MIME type —
you do not need to specify format-specific options. For media sources (images,
video, audio), keep prompts concrete: ask for objects, attributes, timestamps,
or quoted text rather than open-ended descriptions.

## Single Prompt: `run()`

Use `run()` when you have one prompt and at most one source. This is the
starting point for tuning prompt quality before scaling — get one answer right
before multiplying.

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
concurrency, and cache identity automatically. This is where source patterns
(fan-out, fan-in, broadcast) come into play — see
[Analyzing Collections with Source Patterns](source-patterns.md) for
collection-level workflows.

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

## Choosing `run()` vs `run_many()`

| Situation | Use | Why |
|---|---|---|
| One question, optional source | `run()` | Smallest surface area |
| Multiple questions on shared source(s) | `run_many()` | Fan-out efficiency |
| Same question across many sources | `run_many()` | Fan-in analysis |
| Many questions across many sources | `run_many()` | Broadcast pattern |

Rule of thumb: if prompts or sources are plural, use `run_many()`.

`run()` is a convenience wrapper that delegates to `run_many()` with a single
prompt. In benchmarks, `run_many()` is typically faster for multi-prompt
workloads because it shares uploads and runs prompts concurrently.

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
| `usage` | `dict[str, int]` | Yes | Token counts (`input_tokens`, `output_tokens`, `total_tokens`) |
| `metrics` | `dict[str, Any]` | Yes | `duration_s`, `n_calls`, `cache_used` |

Example of a complete envelope:

```python
{
    "status": "ok",
    "answers": ["The paper concludes that..."],
    "confidence": 0.9,
    "extraction_method": "text",
    "usage": {"input_tokens": 1250, "output_tokens": 89, "total_tokens": 1339},
    "metrics": {"duration_s": 1.42, "n_calls": 1, "cache_used": False},
}
```

## Notes

- Conversation continuity (`history`, `continue_from`) supports one
  prompt per call. See
  [Building Conversations and Agent Loops](conversations-and-agents.md).
- `delivery_mode="deferred"` remains reserved and disabled.
- Provider feature support varies. See
  [Provider Capabilities](reference/provider-capabilities.md).
