# Pollux

Ship multimodal analysis fast. Spend less on tokens.

- Get Started → [Quickstart](tutorials/quickstart.md)
- Explore → [Cookbook (recipes)](cookbook.md)

## 30‑second quickstart

```python
import asyncio
from pollux import run_simple, types

async def main():
    envelope = await run_simple(
        "Summarize key insights",
        source=types.Source.from_text("Hello world"),
    )
    print(envelope["answers"][0])

asyncio.run(main())
```

Note: Works without an API key (deterministic mock mode). To use the real API, set `GEMINI_API_KEY` and `POLLUX_USE_REAL_API=1` — see [Verify Real API](how-to/verify-real-api.md).

## Highlights

- Command pipeline: async handler chain for prep → plan → extract → build
- Intelligent batching: group related calls; cut redundant work
- Context caching: up to 75% cost reduction with safe fallbacks
- Multimodal: text, PDFs, images, videos, and YouTube
- Conversation memory: multi‑turn sessions with overflow handling
- Production‑grade: tests, CI, telemetry, and semantic releases

## Choose your path

- New to Pollux: [Quickstart](tutorials/quickstart.md) → [First Batch](tutorials/first-batch.md) → [Cookbook](cookbook.md)
- Going to production: [Installation](how-to/installation.md) → [Configuration](how-to/configuration.md) → [Caching](how-to/caching.md) → [CLI doctor](reference/cli.md) → [Logging](how-to/logging.md)
- Research workflows: [Research](domains/research.md) → [Efficiency workflows](how-to/research/efficiency-workflows.md) → [Extensions catalog](reference/extensions/catalog.md)

## Health check

```bash
pollux-config doctor
```

See: [CLI Reference](reference/cli.md)

## Deep links

- Tutorials: [Quickstart](tutorials/quickstart.md), [First Batch](tutorials/first-batch.md)
- How‑to: [Installation](how-to/installation.md), [Configuration](how-to/configuration.md), [Troubleshooting](how-to/troubleshooting.md)
- Reference: [API overview](reference/api-reference.md), [CLI](reference/cli.md)
- Explanation: [Architecture at a Glance](explanation/architecture.md)
- Project: [Roadmap](roadmap.md), [Project History & GSoC](explanation/history.md)
