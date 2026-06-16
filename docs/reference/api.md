<!-- Intent: Exact signatures for the public Python API. Help readers choose
     the right entry point quickly, then defer to mkdocstrings for field-level
     detail. Do NOT re-teach concepts or workflows already covered in the
     topical guides. Assumes the reader already knows what they want to do.
     Register: reference. -->

# API Reference

Quick reference for the current public API.

For provider-level feature differences, see [Provider Capabilities](provider-capabilities.md).

## Which Entry Point?

| If you want to... | Use | Learn the workflow in... |
|---|---|---|
| Ask one prompt about one source (or no source) | `run()` → `Output` | [Sending Content to Models](../sending-content.md) |
| Ask many prompts against shared sources | `run_many()` → `OutputCollection` | [Analyzing Collections with Source Patterns](../source-patterns.md) |
| Run one explicit interaction (environment + input), incl. tools/continuation | `interact()` | [Building an Agent Loop](../agent-loop.md) |
| Stream one explicit interaction as it arrives | `stream()` → `Event` timeline | [Building an Agent Loop](../agent-loop.md) |
| Prepare a reusable environment (and front-load cache/upload I/O) | `prepare_environment()` → `Environment` | [Reducing Costs with Context Caching](../caching.md) |
| Submit non-urgent work and collect it later | `defer()` → `DeferredHandle` | [Building With Deferred Delivery](../building-with-deferred-delivery.md) |
| Check deferred job status or collect terminal results | `inspect_deferred()` / `collect_deferred()` / `cancel_deferred()` | [Submitting Work for Later Collection](../submitting-work-for-later-collection.md) |

> **2.0 cutover:** `run()` / `run_many()` return the `Output` / `OutputCollection`
> model (named facets, not dict envelopes). `continue_tool()` is replaced by
> `interact(environment, Input(continuation=..., tool_results=...))`; persistent
> caching moves to `prepare_environment()` / `Environment(cache=...)`; and `defer()`
> returns an `OutputCollection` from `collect_deferred()` (the single `defer_many()`
> entry point is removed).

## Entry Points

The primary execution functions are exported from `pollux`:

::: pollux.run

::: pollux.run_many

::: pollux.interact

::: pollux.stream

::: pollux.prepare_environment

::: pollux.defer

::: pollux.inspect_deferred

::: pollux.collect_deferred

::: pollux.cancel_deferred

## Core Types

`Source` includes both the generic source constructors and narrow
provider-specific helpers such as `Source.with_gemini_video_settings(...)` and
`Source.with_gemini_url_context()`.

::: pollux.Source

::: pollux.Config

::: pollux.DeferredHandle

::: pollux.DeferredSnapshot

::: pollux.RetryPolicy

## Interaction Types (2.0)

The canonical v2 interaction model. `interact()` takes an `Environment` and an
`Input` and returns an `Output`; `OutputCollection` is the source-pattern
aggregate that `run_many()` and `collect_deferred()` return. The 1.x `Options`
and `ResultEnvelope` types are no longer part of the public API.

::: pollux.Environment

::: pollux.Input

::: pollux.Output

::: pollux.Event

::: pollux.OutputCollection

::: pollux.OutputRequirements

::: pollux.Continuation

::: pollux.ToolDeclaration

::: pollux.ToolCall

::: pollux.ToolResult

## Error Types

::: pollux.PolluxError

::: pollux.ConfigurationError

::: pollux.SourceError

::: pollux.PlanningError

::: pollux.InternalError

::: pollux.APIError

::: pollux.RateLimitError

::: pollux.CacheError

::: pollux.DeferredNotReadyError
