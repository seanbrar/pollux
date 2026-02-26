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

# Pollux

Multimodal orchestration for LLM APIs. You describe what to analyze. Pollux
handles source patterns, context caching, and the multimodal plumbing.

**Multimodal-first.** PDFs, images, video, YouTube, arXiv. One interface,
any source type.

**Source patterns.** Fan-out, fan-in, and broadcast execution over your
content. No boilerplate.

**Context caching.** Upload once, reuse across prompts. Automatic TTL
management saves tokens and money.

**Built for reliability.** Async pipeline, retries with backoff, structured
output, usage tracking.

## Install

```bash
pip install pollux-ai
```

## Documentation

- [Getting Started](getting-started.md)
- [Core Concepts](concepts.md)
- [Sending Content to Models](sending-content.md)
- [Source Patterns](source-patterns.md)
- [Structured Data](structured-data.md)
- [Conversations and Agents](conversations-and-agents.md)
- [Agent Loop](agent-loop.md)
- [Context Caching](caching.md)
- [Portable Code](portable-code.md)
- [Configuration](configuration.md)
- [Error Handling](error-handling.md)
- [API Reference](reference/api.md)

---

Pollux started as a Google Summer of Code 2025 project with Google DeepMind.
The brightest star in the Gemini constellation.
