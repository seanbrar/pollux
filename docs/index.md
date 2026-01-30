# Pollux

Batch prediction for Gemini. Fewer API calls. Lower costs.

**[Get Started →](guides/quickstart.md)** | [Cookbook](https://github.com/seanbrar/gemini-batch-prediction/tree/main/cookbook)

## 30-Second Example

```python
import asyncio
from pollux import run_simple, types

async def main():
    result = await run_simple(
        "Summarize key insights",
        source=types.Source.from_text("Your content here"),
    )
    print(result["answers"][0])

asyncio.run(main())
```

> Works without an API key (mock mode). Set `GEMINI_API_KEY` and `POLLUX_USE_REAL_API=1` for real calls.

## What It Does

- **Intelligent batching** — N prompts → 1 API call
- **Context caching** — Up to 75% cost reduction
- **Multimodal** — Text, PDFs, images, video, YouTube
- **Conversation memory** — Multi-turn sessions with overflow handling

## Quick Links

| Getting Started | Reference |
|-----------------|-----------|
| [Installation](guides/installation.md) | [API Reference](reference/api-reference.md) |
| [Configuration](guides/configuration.md) | [CLI (`pollux-config`)](reference/cli.md) |
| [Batch Processing](guides/batch-processing.md) | [Configuration Options](reference/configuration.md) |
| [Troubleshooting](guides/troubleshooting.md) | [Glossary](reference/glossary.md) |

## Health Check

```bash
pollux-config doctor
```
