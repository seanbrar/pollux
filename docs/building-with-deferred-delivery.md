<!-- Intent: Teach when deferred delivery is worth using and how to structure
     application code around provider-side job lifecycles. Do NOT reteach the
     deferred method signatures or every lifecycle state in detail. That lives
     on the submission page. Assumes the reader already knows defer(),
     inspect_deferred(), collect_deferred(), and ResultEnvelope. Register:
     guided applied. -->

# Building With Deferred Delivery

You want deferred delivery to pay for itself. This page covers when to choose
it, how to tell when work is done, and what your application should do next.

Deferred delivery is not "slower `run()`." It is a remote job contract. You
submit work now, persist the handle, and collect the result later when the
provider says the job is done. That changes where your code waits and where
your application stores progress.

!!! info "Boundary"
    **Pollux owns:** request normalization, provider submission, handle
    serialization, normalized lifecycle snapshots, and terminal result
    extraction.

    **You own:** deciding that the work can wait, persisting handles, choosing
    polling cadence, deciding what timeout means in your application, and
    wiring collected results into downstream storage or alerts.

## The Operating Pattern

Teach your application three persistence states:

1. `pending`: the job was submitted and the handle is stored durably.
2. `collectable`: `inspect_deferred()` says the job reached a terminal state.
3. `collected`: your code wrote the `ResultEnvelope` somewhere durable and
   retired the pending handle.

That answers the three important questions:

- `inspect_deferred(handle)` tells you whether the provider is done.
- `collect_deferred(handle)` gives you the final Pollux result once it is.
- Your application decides how a pending handle becomes a collected record.

Terminal does not mean successful. A collectable job can still produce
`result["status"] == "partial"` or `result["status"] == "error"`, so branch on
the collected envelope before you decide whether the workflow succeeded.

This pattern fits cleanly inside a larger system. A cron job, worker queue,
CLI, or web app can all use the same boundary. Pollux handles provider
lifecycle calls. Your code owns scheduling and persistence.

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
    defer,
    inspect_deferred,
)

PENDING_DIR = Path("state/deferred/pending")
RESULTS_DIR = Path("state/deferred/results")


def pending_path(job_id: str) -> Path:
    return PENDING_DIR / f"{job_id}.json"


async def submit_reports(paths: list[Path]) -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    for path in paths:
        handle = await defer(
            "Summarize the report in five bullets and list the three biggest execution risks.",
            source=Source.from_file(path),
            config=config,
        )
        record = {
            "report_path": str(path),
            "handle": handle.to_dict(),
        }
        # Persist each handle before moving on to the next submit.
        pending_path(handle.job_id).write_text(
            json.dumps(record, indent=2),
            encoding="utf-8",
        )


async def harvest_ready_reports() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    for record_path in PENDING_DIR.glob("*.json"):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        report_path = Path(record["report_path"])
        handle = DeferredHandle.from_dict(record["handle"])
        snapshot = await inspect_deferred(handle)
        if not snapshot.is_terminal:
            continue

        result = await collect_deferred(handle)
        outcome_dir = RESULTS_DIR / result["status"]
        outcome_dir.mkdir(parents=True, exist_ok=True)
        result_path = outcome_dir / f"{handle.job_id}.json"
        collected = {
            "report_path": str(report_path),
            "snapshot_status": snapshot.status,
            "result": result,
        }
        # Store the collected outcome, then retire the pending handle.
        result_path.write_text(json.dumps(collected, indent=2), encoding="utf-8")
        record_path.unlink()


reports = [Path("reports/q1.pdf"), Path("reports/q2.pdf")]
asyncio.run(submit_reports(reports))
# Later, from another process or scheduled run:
# asyncio.run(harvest_ready_reports())
```

## Why This Shape Works

1. Submission is fast. The interactive path stores a durable handle and exits.
2. Readiness is explicit. `snapshot.is_terminal` is the only gate before
   collection.
3. Success is explicit. `result["status"]` decides whether the collected job
   landed in `ok`, `partial`, or `error`.
4. Collection happens once per pending record. After your code writes the
   outcome, it retires the handle from the pending set.
5. The result still lands in a normal `ResultEnvelope`, so downstream parsing
   stays small.

The directories here are placeholders for your real system boundary. Replace
them with database rows, queue messages, or workflow records if that is how
your application tracks background work.

## When Deferred Is Worth It

- Large fan-out or fan-in work where no person is waiting on the answer.
- Scheduled analysis, backfills, and recurring report generation.
- Provider pricing paths that reward batch-style execution.

Deferred is a poor fit for chat, request-response APIs, or workflows that need
an answer before the current process can continue.

## What To Watch For

- Completion time is provider-driven. A healthy job can stay queued or running
  for much longer than a realtime call.
- A polling timeout is your application's patience limit, not proof that the
  deferred feature failed.
- Cancellation is best-effort. A provider can stay in `cancelling` long after
  you requested it.
- If a process dies after remote acceptance but before it stores the handle,
  treat that submit as ambiguous. Do not blindly resubmit when duplicate work
  would be expensive or confusing.
- Validate your exact provider, model, source type, and schema combination
  before you commit a production workflow to it. Start with single-prompt text.

---

For the exact deferred lifecycle API, see
[Submitting Work for Later Collection](submitting-work-for-later-collection.md).
For recovery patterns when jobs stay active or fail, see
[Handling Errors and Recovery](error-handling.md).
