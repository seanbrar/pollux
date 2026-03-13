<!-- Intent: Teach the deferred workflow for non-urgent jobs: submit,
     persist the handle, inspect status, and collect results later. Do NOT
     teach workflow engines, schedulers, queues, or multi-job orchestration.
     Assumes the reader already knows run(), run_many(), Source, Config, and
     ResultEnvelope. Register: guided applied. -->

# Submitting Work for Later Collection

Some work does not need an answer in the next few seconds. A long fan-out over
large documents, a nightly analysis job, or a backfill across stored reports
fits a different shape: submit now, collect later, and use provider batch
pricing when it is available.

Pollux handles the provider-facing deferred lifecycle. Your application stores
the handle, decides when to poll, and decides what to do with the result.

!!! info "Boundary"
    **Pollux owns:** request normalization, provider submission, stable request
    ids, normalized status snapshots, ordered collection, and extraction into a
    standard `ResultEnvelope`.

    **You own:** handle persistence, polling cadence, scheduling, cross-job
    orchestration, and downstream storage.

## Complete Example

```python
import asyncio
import json
from pathlib import Path

from pollux import (
    Config,
    DeferredHandle,
    Source,
    collect_deferred,
    defer_many,
    inspect_deferred,
)

JOB_PATH = Path("outputs/deferred-job.json")


async def submit_job() -> None:
    config = Config(provider="openai", model="gpt-5-nano")
    handle = await defer_many(
        [
            "Summarize the report in five bullets.",
            "List the three biggest execution risks.",
        ],
        sources=(Source.from_file("market-report.pdf"),),
        config=config,
    )
    JOB_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOB_PATH.write_text(json.dumps(handle.to_dict(), indent=2))
    print(f"saved {handle.job_id} to {JOB_PATH}")


async def collect_job() -> None:
    handle = DeferredHandle.from_dict(json.loads(JOB_PATH.read_text()))
    snapshot = await inspect_deferred(handle)
    print(
        f"status={snapshot.status} "
        f"succeeded={snapshot.succeeded} "
        f"failed={snapshot.failed} "
        f"pending={snapshot.pending}"
    )
    if not snapshot.is_terminal:
        return

    result = await collect_deferred(handle)
    print(result["status"])
    for answer in result["answers"]:
        print(answer)


asyncio.run(submit_job())
# Later, in the same process or a different one:
# asyncio.run(collect_job())
```

Run `submit_job()` once. You should see a provider job id and a JSON file at
`outputs/deferred-job.json`. Run `collect_job()` later. `inspect_deferred()`
normalizes the lifecycle into `queued`, `running`, `cancelling`, `completed`,
`partial`, `failed`, `cancelled`, or `expired`. Once `snapshot.is_terminal`
turns `True`, `collect_deferred()` returns the same `ResultEnvelope` shape that
`run()` and `run_many()` return.

### Why this example is shaped this way

- The handle is the lifecycle record. Persist the full `handle.to_dict()`
  payload, including `provider_state`.
- `inspect_deferred()` takes only the handle. You do not pass `Config` back in.
- Lifecycle calls resolve auth from `handle.provider` and the usual provider
  environment variable. If collection runs in another process, export that key
  there too.
- `DeferredSnapshot.is_terminal` is the stable readiness check. Do not branch on
  one provider's raw status strings.
- `collect_deferred()` is not a polling helper. If the job is still active, it
  raises `DeferredNotReadyError`.
- For a single prompt, use `defer()`. It wraps `defer_many()` the same way
  `run()` wraps `run_many()`.
- Collection preserves prompt order. If you submitted two prompts, the first
  answer still maps to the first prompt.

## Structured Output Across Processes

Deferred collection can still return structured data. Submit with
`Options(response_schema=YourModel)`, then pass the same schema back to
`collect_deferred(handle, response_schema=YourModel)`.

Pollux stores a schema fingerprint in the handle. If the schema changed between
submit and collect, Pollux raises `ConfigurationError` instead of silently
rehydrating into the wrong shape. If you omit `response_schema` at collect
time, Pollux returns plain dicts in `result["structured"]` when the provider
returned structured payloads.

## Current Scope

- Deferred delivery uses dedicated entry points: `defer()`, `defer_many()`,
  `inspect_deferred()`, `collect_deferred()`, and `cancel_deferred()`.
- `run()` and `run_many()` remain realtime entry points. Setting
  `Options(delivery_mode="deferred")` raises `ConfigurationError`.
- Deferred delivery does not support conversation continuity, tool calling,
  persistent cache handles, or implicit caching.
- `cancel_deferred(handle)` requests provider-side cancellation. Final status is
  still provider-driven.

## Deferred Results

Collected deferred jobs return a standard `ResultEnvelope` plus deferred
diagnostics:

- `result["metrics"]["deferred"]` is `True`
- `result["diagnostics"]["deferred"]["job_id"]` identifies the remote job
- `result["diagnostics"]["deferred"]["items"]` includes per-request status,
  finish reason, provider status, and any item-level error text

Those are deferred-only additions on top of the standard envelope shape
documented in [ResultEnvelope Reference](sending-content.md#resultenvelope-reference).

That keeps downstream code small. Your post-processing path can usually treat
realtime and deferred results the same way.

---

Next, read [Handling Errors and Recovery](error-handling.md) for retry policy
and error types, or check [Provider Capabilities](reference/provider-capabilities.md)
to see which providers support deferred delivery in the current release.
