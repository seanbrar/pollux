# Quick Start

Get your first answer in under 2 minutes.

## 1) Install

```bash
pip install pollux
```

Or download the latest wheel from
[Releases](https://github.com/seanbrar/pollux/releases/latest).

## 2) Set your API key

Get a key from [Google AI Studio](https://ai.dev/), then:

```bash
export GEMINI_API_KEY="your-key-here"
```

## 3) Run

```python
import asyncio
from pollux import Config, Source, run

async def main() -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")
    result = await run(
        "What are the key points?",
        source=Source.from_file("document.pdf"),
        config=config,
    )
    print(result["answers"][0])

asyncio.run(main())
```

Expected result: a short answer printed to your terminal.

## Next Steps

- **[Usage Patterns](guides/patterns.md)** — Single-call and batched execution patterns
- **[Configuration](guides/configuration.md)** — Models, tiers, and options
- **[Provider Capabilities](reference/provider-capabilities.md)** — Provider-specific features and limits
- **[Cookbook](cookbook/index.md)** — Ready-to-run recipes
