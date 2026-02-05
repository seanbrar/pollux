# Resume on Failure

Persist progress so reruns process only unfinished work.

## At a glance

- **Best for:** long jobs where occasional failures are expected.
- **Input:** directory, manifest path, output directory.
- **Output:** durable per-item status + resumable retries.

## Command

Initial run:

```bash
python -m cookbook production/resume-on-failure -- \
  --input ./docs --limit 10 --manifest outputs/manifest.json
```

Resume failed items:

```bash
python -m cookbook production/resume-on-failure -- \
  --input ./docs --failed-only --manifest outputs/manifest.json
```

## Expected signal

- Manifest is updated after each processed item.
- Per-item result artifacts appear in `--output-dir`.
- `--failed-only` skips previously successful items.

## Interpret the result

- Rising error counts indicate either retry policy issues or bad inputs.
- Frequent partial statuses suggest prompt/input or provider instability.
- Manifest is your source of truth for job state.

## Common pitfalls

- Unstable item IDs between runs.
- Writing manifest too infrequently.
- Retrying non-retriable validation failures.

## Try next

- Split retry policies by error category.
- Export manifest metrics to monitoring dashboards.
