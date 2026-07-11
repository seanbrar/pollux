<!-- Intent: Guide Pollux 1.x users to the shipped 2.0 release-candidate API.
     Teach what stayed familiar, what changed, and how to migrate without
     implying that the RC has stable-release guarantees. Assumes the reader
     has used Pollux 1.x. Register: warm guide with precise caveats. -->

# Migrating to Pollux 2.0

!!! warning "Release candidate"
    Pollux 2.0 is available as a release candidate, not a stable release. The
    API on this page is shipped in the RC and on `main`, but interaction details
    may still change before stable 2.0. Install it with
    `pip install --pre --upgrade pollux-ai`.

Pollux 2.0 is a major-version cleanup of the interaction model. It names the
pieces of a model interaction directly: the environment the model runs in, the
input for this turn, the output requirements, and the continuation state that
carries work forward.

Most one-shot code should remain recognizable. The bigger changes affect code
that builds agent loops, persists continuation state, prepares caches, submits
deferred collections, or reaches into result dictionaries.

## Who Is Affected

You should read this page if your 1.x code uses any of these:

- `Options(...)` for output shape, tools, reasoning, caching, or provider
  controls.
- The removed `Options.delivery_mode` setting. Use `run()` /
  `run_many()` for realtime calls and `defer()` for provider-side deferred work.
- `continue_from`, `history`, `continue_tool()`, or persisted continuation
  blobs.
- `create_cache(...)` and explicit cache handles.
- `defer_many(...)`.
- Dictionary-style result access such as `result["text"]`.

If your code calls `run()` with a prompt, sources, and config, the migration is
small.

## What Stays Familiar

These entry points keep their 1.x role:

- `run()` for one realtime interaction.
- `run_many()` for source-pattern collections: fan-out, fan-in, and broadcast.
- `defer()` for provider-side work that you submit now and collect later.
- `inspect_deferred()`, `collect_deferred()`, and `cancel_deferred()` for the
  deferred lifecycle.

In other words, the first Pollux program still starts with `run()`.

## What Changes

The changes move behavior out of special-case helpers and into named
interaction pieces.

| 1.x | 2.0 RC shape | Why |
| --- | --- | --- |
| `Options(...)` | `Environment`, `Input`, and `OutputRequirements` | Provider, turn input, and output contract become separate objects. |
| `continue_tool(env, results)` | `interact(environment, Input(continuation=..., tool_results=...))` | Tool-result replay becomes part of continuing an interaction. |
| `create_cache(...)` | Prepared `Environment` | Cache identity belongs with the model environment that will reuse it. |
| `defer_many(...)` | `defer(...)` | Deferred submission uses one entry point for one interaction or a collection. |
| `result["text"]` | `result.text` | Results become typed outputs with named facets and explicit serialization. |

## Before And After

Here is the expected direction for result handling:

```python
# 1.x
text = result["text"]
payload = dict(result)

# 2.0 RC
text = result.text
payload = result.to_jsonable()
```

Tool loops are expected to move from a helper-shaped API to an
interaction-shaped API:

```python
# 1.x
next_result = await continue_tool(env, tool_results)

# 2.0 RC
next_result = await interact(
    environment,
    Input(continuation=continuation, tool_results=tool_results),
)
```

The important shift is ownership. Your code still owns tool execution, approval,
logging, limits, and storage. Pollux owns the provider-facing interaction and
the continuation format it needs for the next turn.

## Serialized State

In 2.0, continuation state is the public `Continuation` primitive, not a private
dict. Read it from `output.continuation`, persist it with
`continuation.to_jsonable()`, and restore it with `Continuation.from_jsonable(...)`.
Serialized continuations are stamped with a schema version and the provider that
produced them, and `from_jsonable()` rejects an incompatible version (and, when you
pass `expected_provider=`, a mismatched provider) with an actionable error instead
of misreading it.

A continuation is bound to its provider: its `provider_state` (response ids,
provider-specific replay blocks) is not portable, so reusing one under a different
provider is rejected before dispatch. Across the 1.x → 2.0 boundary, plan to re-run
work rather than reusing old serialized blobs; persist enough application state to
rebuild the request when that is the right recovery path.

## What To Do In 1.x

You do not need to migrate working 1.x code while 2.0 is in RC. When you are
ready to test the RC:

- Keep provider setup, prompts, sources, and output requirements separated in
  your own code.
- Prefer public result fields and documented envelope behavior over ad hoc
  dictionary probing.
- Treat continuation blobs and deferred handles as Pollux-owned artifacts.
  Store them, but do not inspect or mutate their internals.
- Keep tool execution policy in your application code: dispatch, approval,
  logging, retries, and stop conditions.
- Use `run()` and `run_many()` for realtime source patterns, and `defer()`
  only when provider-side deferred delivery is the workflow you want.

## What Is Available In The RC

The 2.0 interaction model is available in `v2.0.0-rc.1` and on `main`:

- `run()` and `run_many()` now return the 2.0 result model: `run()` returns an
  `Output` (named facets `text`, `structured`, `reasoning`, `tool_calls`,
  `continuation`, `usage`, `metrics`, `diagnostics`); `run_many()` returns an
  `OutputCollection` (`.answers`, `.structured`, `.status`, `.usage`). They take
  first-class keyword arguments (`instructions=`, `output=`, `temperature=`,
  `max_tokens=`, `tools=`, …) instead of an `Options` object. Read facets
  (`result.text`) rather than dictionary keys (`result["answers"][0]`).
- `interact(environment, input, *, config, **generation_kwargs) -> Output` runs
  one explicit interaction over an `Environment` and `Input`. Continue a
  conversation or tool loop by passing the prior `Output`'s `continuation` and any
  `tool_results` in the next `Input`, the replacement for `continue_tool()`.
- `stream(environment, input, *, config, **generation_kwargs)` observes that same
  interaction as a timeline of `Event`s (`text_delta`, `reasoning_delta`,
  `tool_call`, `usage`, `finish`), ending in a `done` event whose `output` matches
  what `interact()` would return. Streaming is supported on every provider.

`defer()` now follows the same model: it accepts one prompt or a collection,
and `collect_deferred()` returns an `OutputCollection`. Persistent caching
returns through `prepare_environment()` / `Environment(cache=...)`.
`create_cache()`, `defer_many()`, and `Options` are removed.

## During The RC Cycle

This page is the public migration contract for the release-candidate cycle. It
will track any deliberate pre-stable changes so downstream developers can test
the exact API that is being prepared for stable 2.0.

---

For the concepts behind the model, read [Core Concepts](concepts.md).
For the current provider contract, see
[Provider Capabilities](reference/provider-capabilities.md).
