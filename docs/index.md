# Pollux

Multimodal orchestration for Gemini.

> You describe what to analyze. Pollux handles source patterns, context caching, and multimodal complexity—so you don't.

```python
import asyncio
from pollux import Config, Source, run

async def main() -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")
    result = await run(
        "What are the key findings?",
        source=Source.from_file("paper.pdf"),
        config=config,
    )
    print(result["answers"][0])

asyncio.run(main())
```

## Why Pollux?

- **Multimodal-first** — PDFs, images, videos, YouTube URLs. Same API.
- **Source patterns** — Fan-out (one source → many prompts), fan-in, and broadcast.
- **Context caching** — Upload once, reuse across prompts. Save tokens and money.
- **Production-ready core** — Async execution, explicit capability checks, clear errors.

## Get Started

**[Quickstart →](quickstart.md)** — First result in 2 minutes

**[Guides →](guides/installation.md)** — Installation, configuration, patterns

**[Cookbook](cookbook/index.md)** — Scenario-driven, ready-to-run recipes

**[Provider Capabilities](reference/provider-capabilities.md)** — Provider-by-provider feature matrix
