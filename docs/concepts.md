# Concepts

This page gives the mental model behind Pollux so usage decisions feel
predictable instead of trial-and-error.

## What Pollux Solves

Pollux is an orchestration layer for multimodal LLM analysis.

You describe what to analyze. Pollux handles:

- source pattern execution (`fan-out`, `fan-in`, `broadcast`)
- provider-side context caching (when available)
- request concurrency and retries
- provider-specific request shaping and result normalization

## Core Vocabulary

Use these terms consistently:

- **Context caching**: upload content once, reuse across prompts.
- **Fan-out**: one source -> many prompts.
- **Fan-in**: many sources -> one prompt.
- **Broadcast**: many sources x many prompts.
- **Source patterns**: fan-out, fan-in, broadcast collectively.
- **Deferred mode**: future provider async batch API mode (reserved in v1.0).

Need quick definitions while reading? See the [Glossary](glossary.md).

## Pipeline Mental Model

Every call follows the same four-phase pipeline:

1. **Request**
   - normalize prompts, sources, config, and options.
2. **Plan**
   - build deterministic execution calls and cache identities.
3. **Execute**
   - upload content, reuse cache where possible, run provider calls.
4. **Extract**
   - return a stable `ResultEnvelope` (`answers`, optional `structured`, `usage`, `metrics`).

This separation is why Pollux can support multimodal inputs and provider
differences without forcing callers to reimplement orchestration logic.

## Choosing the Right Entry Point

| Situation | API |
|---|---|
| One prompt, optional source | `run()` |
| Multiple prompts and/or shared sources | `run_many()` |

`run()` is a convenience path that delegates to `run_many()` with one prompt.

## Source Pattern Tradeoffs

### Fan-out

- Best for: repeated questions about one artifact (paper/video/image).
- Why: strongest context caching and upload reuse benefits.

### Fan-in

- Best for: synthesis/comparison across multiple artifacts.
- Why: single prompt over multiple sources keeps the comparison objective stable.

### Broadcast

- Best for: standardized analysis templates across many sources.
- Why: consistent prompt sets make output comparison and post-processing easier.

## Context Caching: Cost and Latency Intuition

Without caching, repeated questions resend the same large context each time.
With caching, context is uploaded once and reused.

Caching pays off when:

- sources are large
- prompt sets are repeated
- reuse happens inside cache TTL windows

Caching is provider-dependent. Check
[Provider Capabilities](reference/provider-capabilities.md).

## Capability Transparency

Pollux does not hide provider differences behind silent fallbacks.

Instead:

- supported features run normally
- unsupported combinations fail fast with clear `ConfigurationError`/`APIError`

This keeps behavior legible in both local development and production.

## What You Own vs What Pollux Owns

You own:

- prompt intent and output criteria
- source selection and quality
- model/provider choice
- domain-specific validation of outputs

Pollux owns:

- orchestration mechanics
- cache identity/reuse plumbing
- retry and concurrency control
- normalized output envelope

## Next Steps

- [Quickstart](quickstart.md)
- [Usage Patterns](guides/patterns.md)
- [Token Efficiency](guides/token-efficiency.md)
- [Provider Capabilities](reference/provider-capabilities.md)
