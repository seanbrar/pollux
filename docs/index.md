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
- **Built for reliability** — Async execution, retries, concurrency control, and actionable errors.

## Install

```bash
pip install pollux-ai
```

## Where to Go Next

- **[Getting Started](getting-started.md)** — First result in 2 minutes
- **[Core Concepts](concepts.md)** — LLM orchestration concepts and Pollux's pipeline
- **[Sending Content to Models](sending-content.md)** — Source constructors, `run()` vs `run_many()`, and the result envelope
- **[Analyzing Collections with Source Patterns](source-patterns.md)** — Fan-out, fan-in, and broadcast workflows
- **[Extracting Structured Data](structured-data.md)** — Typed output via Pydantic schemas
- **[Building Conversations and Agent Loops](conversations-and-agents.md)** — Multi-turn chat and tool calling
- **[Reducing Costs with Context Caching](caching.md)** — Upload once, reuse across prompts
- **[Writing Portable Code Across Providers](portable-code.md)** — Switch providers by changing one config line
- **[Configuring Pollux](configuration.md)** — Config fields, API key resolution, retry, and mock mode
- **[Handling Errors and Recovery](error-handling.md)** — Exception hierarchy and production error patterns
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
