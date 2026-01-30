# Quickstart

Get your first result in 2 minutes.

## 1. Install

```bash
pip install pollux
```

Or download the latest wheel from [Releases](https://github.com/seanbrar/gemini-batch-prediction/releases/latest).

## 2. Set your API key

Get a key from [Google AI Studio](https://ai.dev/), then:

```bash
export GEMINI_API_KEY="your-key-here"
```

## 3. Run

```python
import asyncio
from pollux import run_simple, types

async def main():
    result = await run_simple(
        "What are the key points?",
        source=types.Source.from_file("document.pdf"),
    )
    print(result["answers"][0])

asyncio.run(main())
```

That's it. You'll see Gemini's response printed.

## Next steps

- **[Batch processing](guides/batch-processing.md)** — Process multiple files or prompts
- **[Configuration](guides/configuration.md)** — Set model, tier, caching options
- **[Cookbook](https://github.com/seanbrar/gemini-batch-prediction/tree/main/cookbook)** — Real-world recipes
