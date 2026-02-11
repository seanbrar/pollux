# Quick Start

Get your first answer in under 2 minutes.

## Use this page when

- you want the fastest path to a working Pollux call
- you prefer one happy-path example before exploring alternatives

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

Success check:

- call completes without exceptions
- output is specific to your input source (not generic boilerplate)

## Next Steps

- **[Concepts](concepts.md)** — Mental model for source patterns and context caching
- **[Usage Patterns](guides/patterns.md)** — Single-call and multi-prompt execution patterns
- **[Configuration](guides/configuration.md)** — Providers, models, and options
- **[Provider Capabilities](reference/provider-capabilities.md)** — Provider-specific features and limits
- **[Cookbook](cookbook/index.md)** — Ready-to-run recipes
