# Resume on Failure

Persist manifest state so retries process only unfinished or failed work.

## At a glance

- **Best for:** long-running jobs where partial failures are expected.
- **Input:** directory + manifest path + output directory.
- **Output:** durable per-item statuses and resumable reruns.

## Before you run

- Use a stable input directory between retries.
- Keep manifest and output artifacts in persistent storage.

## Command

Initial run:

```bash
python -m cookbook production/resume-on-failure -- \
  --input cookbook/data/demo/text-medium --limit 4 \
  --manifest outputs/manifest.json --output-dir outputs/items --mock
```

Retry only unresolved items:

```bash
python -m cookbook production/resume-on-failure -- \
  --input cookbook/data/demo/text-medium --failed-only \
  --manifest outputs/manifest.json --output-dir outputs/items --mock
```

## What to look for

- Manifest updates after each item (not only at run end).
- Re-runs with `--failed-only` skip previously `ok` work.
- Per-item JSON artifacts preserve answers, usage, and metrics.

## Tuning levers

- `--max-retries` and `--backoff-seconds` control retry aggressiveness.
- `--limit` sets workload size for staged production rollout.

## Failure modes

- Changing item identity logic breaks resumability.
- Writing manifest too infrequently risks progress loss.
- Retrying non-retriable validation errors wastes time/cost.

## Extend this recipe

- Split retries by error category (rate-limit vs validation).
- Export manifest rollups to dashboards for operational visibility.

