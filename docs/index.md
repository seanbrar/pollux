# Pollux

**Multimodal orchestration for LLM APIs.** You describe what to analyze.
Pollux handles source patterns, context caching, and multimodal
complexity — so you don't.

## Why Pollux?

- **Multimodal-first** — PDFs, images, videos, YouTube URLs. Same API.
- **Source patterns** — Fan-out, fan-in, and broadcast execution over your content.
- **Context caching** — Upload once, reuse across prompts. Save tokens and money.
- **Production-ready core** — Async pipeline, explicit capability checks, clear errors.

## Install

```bash
pip install pollux
```

```python
import asyncio
from pollux import Config, Source, run

result = asyncio.run(
    run(
        "What are the key findings?",
        source=Source.from_text(
            "Pollux supports fan-out, fan-in, and broadcast source patterns. "
            "It also supports context caching for repeated prompts."
        ),
        config=Config(provider="gemini", model="gemini-2.5-flash-lite"),
    )
)
print(result["answers"][0])
```

## Where to Go Next

- **[Quickstart](quickstart.md)** — First result in 2 minutes
- **[Concepts](concepts.md)** — Mental model for the pipeline and source patterns
- **[Cookbook](cookbook/index.md)** — Scenario-driven, ready-to-run recipes
- **[API Reference](reference/api.md)** — Entry points and types

---

## About Pollux {: #about }

Pollux began as a Google Summer of Code 2025 project with Google DeepMind.
The goal: make multimodal analysis on Gemini efficient, reliable, and
accessible.

The project has since evolved into a production-ready library, but the
research-minded approach remains. Every design decision is deliberate; every
abstraction was earned, not assumed.

**The name:** Pollux is the brightest star in the Gemini constellation. The
library clears away infrastructure complexity so Gemini's capabilities reach
your code cleanly.

**Acknowledgments:** Google Summer of Code 2025, Google DeepMind mentorship.
