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
| Submit non-urgent work and collect it later | `defer()` / `defer_many()` | [Building With Deferred Delivery](../building-with-deferred-delivery.md) |
| Check deferred job status or collect terminal results | `inspect_deferred()` / `collect_deferred()` / `cancel_deferred()` | [Submitting Work for Later Collection](../submitting-work-for-later-collection.md) |

> **2.0 cutover:** `run()` / `run_many()` now return the `Output` / `OutputCollection`
> model (named facets, not dict envelopes). `continue_tool()` is replaced by
> `interact(environment, Input(continuation=..., tool_results=...))`, and persistent
> caching moves to environment preparation (a later 2.0 change).

## Entry Points

The primary execution functions are exported from `pollux`:

::: pollux.run

::: pollux.run_many

::: pollux.interact

::: pollux.defer

::: pollux.defer_many

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

::: pollux.Options

::: pollux.RetryPolicy

::: pollux.ResultEnvelope

## Interaction Types (2.0)

The canonical v2 interaction model. `interact()` takes an `Environment` and an
`Input` and returns an `Output`; `OutputCollection` is the source-pattern
aggregate. These coexist with the 1.x types during the 2.0 cutover.

::: pollux.Environment

::: pollux.Input

::: pollux.Output

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
