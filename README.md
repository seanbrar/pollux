<!-- Intent: Repository landing page for first-time users. Get the reader to a
     working result quickly, then show the three execution shapes they are most
     likely to need: single-call realtime, source-pattern realtime, and
     deferred delivery. Do NOT reteach lifecycle details, provider caveats, or
     architecture concepts that already live in the docs. Assumes the reader
     knows what an LLM API is and is deciding whether to try Pollux. Register:
     landing copy. -->

# Pollux

Multimodal orchestration for LLM APIs.

> You describe what to analyze. Pollux handles source patterns, context caching, deferred delivery, and multimodal content.

[Documentation](https://polluxlib.dev/) ·
[Getting Started](https://polluxlib.dev/getting-started/) ·
[Building With Deferred Delivery](https://polluxlib.dev/building-with-deferred-delivery/)

[![PyPI](https://img.shields.io/pypi/v/pollux-ai)](https://pypi.org/project/pollux-ai/)
[![CI](https://github.com/seanbrar/pollux/actions/workflows/ci.yml/badge.svg)](https://github.com/seanbrar/pollux/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/seanbrar/pollux/graph/badge.svg)](https://codecov.io/gh/seanbrar/pollux)
[![Testing: MTMT](https://img.shields.io/badge/testing-MTMT_v0.1.0-blue)](https://github.com/seanbrar/minimal-tests-maximum-trust)
![Python](https://img.shields.io/badge/Python-3.10%2B-brightgreen)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Quick Start

```python
import asyncio
from pollux import Config, Source, run

result = asyncio.run(
    run(
        "What are the key findings and their implications?",
        source=Source.from_file("earnings-report.pdf"),
        config=Config(provider="gemini", model="gemini-2.5-flash-lite"),
    )
)
print(result["answers"][0])
# Revenue grew 18% YoY to $4.2B, driven by cloud services. Operating
# margins improved from 29% to 34%. Management's $2B buyback and raised
# guidance signal confidence in sustained growth.
```

`run()` returns a `ResultEnvelope`: `answers` holds one entry per prompt.

To use OpenAI instead: `Config(provider="openai", model="gpt-5-nano")`.<br>
For Anthropic: `Config(provider="anthropic", model="claude-haiku-4-5")`.<br>
For OpenRouter: `Config(provider="openrouter", model="google/gemma-3-27b-it:free")`.

For a full walkthrough (install, key setup, first result), see
[Getting Started](https://polluxlib.dev/getting-started/).

## Which Entry Point Should I Use?

| If you want to... | Use |
|---|---|
| Ask one prompt and get an answer now | `run()` |
| Ask many prompts against shared source(s) | `run_many()` |
| Submit non-urgent work and collect it later | `defer()` / `defer_many()` |

Pollux keeps realtime and deferred work on separate entry points. If the result
can wait, submit it once, persist the handle, and collect the same
`ResultEnvelope` later.

## What Pollux Handles

Say you have a document and ten questions about it. Each API call re-uploads the file, and you're left managing caching, retries, and concurrency yourself. Pollux uploads once, caches the content, fans out your prompts concurrently, and hands back results.

The same `Source` interface handles PDFs, images, video, YouTube URLs, and arXiv papers. No per-format upload code.

Need structured output? Pass a Pydantic model as `response_schema` and get a validated instance alongside the raw text. Switching providers is a one-line change: `provider="gemini"` to `provider="openai"`.

## One Upload, Many Prompts

Got three questions about the same paper? `run_many()` fans them out concurrently:

```python
import asyncio
from pollux import Config, Source, run_many

envelope = asyncio.run(
    run_many(
        ["Summarize the methodology.", "List key findings.", "Identify limitations."],
        sources=[Source.from_file("paper.pdf")],
        config=Config(provider="gemini", model="gemini-2.5-flash-lite"),
    )
)
for answer in envelope["answers"]:
    print(answer)
```

Add more sources and Pollux broadcasts every prompt across every source, uploading each once regardless of how many prompts reference it.

## When the Work Can Wait

Deferred delivery is for long fan-out work, backfills, and scheduled analysis
where no one is waiting on the answer in the current process.

```python
import asyncio
from pollux import (
    Config,
    Source,
    collect_deferred,
    defer,
    inspect_deferred,
)

config = Config(provider="openai", model="gpt-5-nano")

handle = asyncio.run(
    defer(
        "Summarize the report in five bullets.",
        source=Source.from_file("market-report.pdf"),
        config=config,
    )
)

snapshot = asyncio.run(inspect_deferred(handle))
if snapshot.is_terminal:
    result = asyncio.run(collect_deferred(handle))
    print(result["answers"][0])
```

In production code, persist `handle.to_dict()` and restore it later with
`DeferredHandle.from_dict(...)`. For the full lifecycle, read
[Submitting Work for Later Collection](https://polluxlib.dev/submitting-work-for-later-collection/)
and
[Building With Deferred Delivery](https://polluxlib.dev/building-with-deferred-delivery/).

## Where Pollux Ends

Pollux owns content delivery, context caching, and provider translation. Prompt design, workflow orchestration, and what you do with results are yours. See [Core Concepts](https://polluxlib.dev/concepts/) for the full boundary model.

## Installation

```bash
pip install pollux-ai
```

Set your provider's API key:

```bash
export GEMINI_API_KEY="your-key-here"     # or
export OPENAI_API_KEY="your-key-here"     # or
export ANTHROPIC_API_KEY="your-key-here"  # or
export OPENROUTER_API_KEY="your-key-here"
```

Keys from: [Google AI Studio](https://ai.dev/) · [OpenAI](https://platform.openai.com/api-keys) · [Anthropic](https://console.anthropic.com/settings/keys) · [OpenRouter](https://openrouter.ai/keys)

## Documentation

- [Getting Started](https://polluxlib.dev/getting-started/): first result in 2 minutes
- [Core Concepts](https://polluxlib.dev/concepts/): mental model and vocabulary
- [Submitting Work for Later Collection](https://polluxlib.dev/submitting-work-for-later-collection/): deferred lifecycle API
- [Building With Deferred Delivery](https://polluxlib.dev/building-with-deferred-delivery/): when deferred is worth it
- [API Reference](https://polluxlib.dev/reference/api/): entry points and types
- [Cookbook](https://polluxlib.dev/reference/cli/): runnable end-to-end recipes

Full docs at [polluxlib.dev](https://polluxlib.dev/).

## Contributing

See [CONTRIBUTING](https://polluxlib.dev/contributing/) and [TESTING.md](./TESTING.md) for guidelines.

Built during [Google Summer of Code 2025](https://summerofcode.withgoogle.com/) with Google DeepMind. [Learn more](https://polluxlib.dev/#about)

## License

[MIT](LICENSE)
