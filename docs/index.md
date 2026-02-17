---
title: Pollux
template: home.html
hide:
  - navigation
  - toc
  - path
---

<!-- SEO fallback: this Markdown body is not rendered visually (the content
     block is suppressed by home.html) but crawlers will index the text. -->

# Pollux — Multimodal orchestration for LLM APIs

**Multimodal orchestration for LLM APIs.** You describe what to analyze.
Pollux handles source patterns, context caching, and multimodal
complexity — so you don't.

## Why Pollux?

- **Multimodal-first** — PDFs, images, video, YouTube URLs, and arXiv papers. Same API.
- **Source patterns** — Fan-out, fan-in, and broadcast execution over your content.
- **Context caching** — Upload once, reuse across prompts. Save tokens and money.
- **Structured output** — Get typed responses via Pydantic schemas.
- **Built for reliability** — Async execution, retries, concurrency control, and clear errors.

## Install

```bash
pip install pollux-ai
```

## Where to Go Next

- **[Quickstart](quickstart.md)** — First result in 2 minutes
- **[Concepts](concepts.md)** — Mental model for the pipeline and source patterns
- **[Sources and Patterns](sources-and-patterns.md)** — Source constructors, `run()` vs `run_many()`, and the result envelope
- **[Configuration](configuration.md)** — Config fields, API key resolution, retry, and mock mode
- **[Cookbook](cookbook/index.md)** — Scenario-driven, ready-to-run recipes
- **[Troubleshooting](troubleshooting.md)** — Fast fixes for common setup and runtime issues
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
