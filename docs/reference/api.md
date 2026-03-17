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
| Ask one prompt about one source (or no source) | `run()` | [Sending Content to Models](../sending-content.md) |
| Ask many prompts against shared sources | `run_many()` | [Analyzing Collections with Source Patterns](../source-patterns.md) |
| Submit non-urgent work and collect it later | `defer()` / `defer_many()` | [Building With Deferred Delivery](../building-with-deferred-delivery.md) |
| Check deferred job status or collect terminal results | `inspect_deferred()` / `collect_deferred()` / `cancel_deferred()` | [Submitting Work for Later Collection](../submitting-work-for-later-collection.md) |
| Feed tool results back into a conversation turn | `continue_tool()` | [Building an Agent Loop](../agent-loop.md) |
| Reuse Gemini context across later calls | `create_cache()` | [Reducing Costs with Context Caching](../caching.md) |

## Entry Points

The primary execution functions are exported from `pollux`:

::: pollux.run

::: pollux.run_many

::: pollux.defer

::: pollux.defer_many

::: pollux.inspect_deferred

::: pollux.collect_deferred

::: pollux.cancel_deferred

::: pollux.continue_tool

::: pollux.create_cache

## Core Types

::: pollux.Source

::: pollux.CacheHandle

::: pollux.Config

::: pollux.DeferredHandle

::: pollux.DeferredSnapshot

::: pollux.Options

::: pollux.RetryPolicy

::: pollux.ResultEnvelope

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
