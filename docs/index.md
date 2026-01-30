# Pollux

Efficient multimodal analysis on Google's Gemini API.

> You describe what to analyze. Pollux handles batching, caching, rate limits, and retries—so you don't.

```python
import asyncio
from pollux import run_simple, types

async def main():
    result = await run_simple(
        "What are the key findings?",
        source=types.Source.from_file("paper.pdf"),
    )
    print(result["answers"][0])

asyncio.run(main())
```

## Why Pollux?

- **Multimodal-first** — PDFs, images, videos, YouTube URLs. Same API.
- **Intelligent batching** — Fan-out across prompts and sources efficiently.
- **Context caching** — Reuse uploaded content. Save tokens and money.
- **Production-ready** — Rate limiting, retries, async pipelines.

## Get Started

**[Quickstart →](quickstart.md)** — First result in 2 minutes

**[Guides →](guides/installation.md)** — Installation, configuration, patterns

**[Cookbook](https://github.com/seanbrar/pollux/tree/main/cookbook)** — 11 ready-to-run recipes
