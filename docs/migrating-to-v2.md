<!-- Intent: Preview the planned Pollux 2.0 migration path for 1.x users.
     Teach what is expected to stay familiar, what is expected to move, and
     what users can do in 1.x to reduce future churn. Do NOT present the v2 API
     as final or require users to rewrite code before v2 is released. Assumes
     the reader has used Pollux 1.x. Register: warm guide with precise caveats. -->

# Migrating to Pollux 2.0

!!! warning "Planned, not released"
    Pollux 2.0 has not shipped. This page describes the migration direction so
    you can write 1.x code with less future churn. Names, signatures, and exact
    replacement snippets may change before release.

Pollux 2.0 is planned as a major-version cleanup of the interaction model. The
goal is to name the pieces of a model interaction directly: the environment the
model runs in, the input for this turn, the output requirements, and the
continuation state that carries work forward.

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
expected to be small.

## What Stays Familiar

These 1.x entry points are expected to keep their role:

- `run()` for one realtime interaction.
- `run_many()` for source-pattern collections: fan-out, fan-in, and broadcast.
- `defer()` for provider-side work that you submit now and collect later.
- `inspect_deferred()`, `collect_deferred()`, and `cancel_deferred()` for the
  deferred lifecycle.

In other words, the first Pollux program still starts with `run()`.

## What Changes

The planned changes move behavior out of special-case helpers and into named
interaction pieces. Treat the right column as migration direction until the v2
API lands.

| 1.x | Planned 2.0 shape | Why |
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

# 2.0 planned shape
text = result.text
payload = result.to_jsonable()
```

Tool loops are expected to move from a helper-shaped API to an
interaction-shaped API:

```python
# 1.x
next_result = await continue_tool(env, tool_results)

# 2.0 planned shape
next_result = await interact(
    environment,
    Input(continuation=continuation, tool_results=tool_results),
)
```

The important shift is ownership. Your code still owns tool execution, approval,
logging, limits, and storage. Pollux owns the provider-facing interaction and
the continuation format it needs for the next turn.

## Serialized State

Pollux 1.x now stamps serialized continuation state and deferred handles with a
version and provider marker. Pollux 2.0 is expected to reject incompatible 1.x
artifacts with an actionable error instead of reading them as 2.0 state.

Plan to re-run work across the major-version boundary rather than reusing old
serialized continuation blobs. Persist enough application state to rebuild the
request when that is the right recovery path.

## What To Do In 1.x

You do not need to rewrite working 1.x code before 2.0 exists. To make future
migration easier:

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

## What Is Available Now

The 2.0 interaction model is landing incrementally on `main`:

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

`defer()` now follows the same model: it accepts one prompt or a collection,
and `collect_deferred()` returns an `OutputCollection`. Persistent caching
returns through `prepare_environment()` / `Environment(cache=...)`.
`create_cache()`, `defer_many()`, and `Options` are removed.

## As The Design Settles

This page will change as the 2.0 API moves from plan to release candidate. Use
it as the public migration guide; exact replacement snippets will become more
specific as names and signatures settle.

---

For the concepts behind the planned model, read [Core Concepts](concepts.md).
For the current provider contract, see
[Provider Capabilities](reference/provider-capabilities.md).
