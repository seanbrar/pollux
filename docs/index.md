# Pollux

Multimodal orchestration for LLM APIs.

> You describe what to analyze. Pollux handles source patterns, context caching, and multimodal complexity—so you don't.
>
> Originally built for Gemini during Google Summer of Code 2025. Pollux now
> supports both Gemini and OpenAI with explicit capability differences.

## Why Pollux?

- **Multimodal-first** — PDFs, images, videos, YouTube URLs. Same API.
- **Source patterns** — Fan-out (one source → many prompts), fan-in, and broadcast.
- **Context caching** — Upload once, reuse across prompts. Save tokens and money.
- **Production-ready core** — Async execution, explicit capability checks, clear errors.

## Get Started

**[Quickstart →](quickstart.md)** — First result in 2 minutes

**[Concepts →](concepts.md)** — Mental model for source patterns and caching

**[Guides →](guides/installation.md)** — Installation, configuration, patterns

**[Cookbook](cookbook/index.md)** — Scenario-driven, ready-to-run recipes

**[Provider Capabilities](reference/provider-capabilities.md)** — Provider-by-provider feature matrix

## Choose Your Path

- **Evaluating fit**: start with [Concepts](concepts.md), then [Provider Capabilities](reference/provider-capabilities.md)
- **Building quickly**: follow [Quickstart](quickstart.md), then [Usage Patterns](guides/patterns.md)
- **Optimizing and operating**: use [Token Efficiency](guides/token-efficiency.md), [Caching](guides/caching.md), then [Cookbook](cookbook/index.md)
