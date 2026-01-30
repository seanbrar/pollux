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
from pollux import run_simple, types

async def main() -> None:
    result = await run_simple(
        "What are the key points?",
        source=types.Source.from_file("document.pdf"),
    )
    print(result["answers"][0])

asyncio.run(main())
```

Expected result: a short answer printed to your terminal.

## Next Steps

- **[Usage Patterns](guides/patterns.md)** — Batch processing, conversations
- **[Configuration](guides/configuration.md)** — Models, tiers, and options
- **[Cookbook](https://github.com/seanbrar/pollux/tree/main/cookbook)** — Ready-to-run recipes
