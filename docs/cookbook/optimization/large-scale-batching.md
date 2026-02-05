# Large-Scale Batching

Fan out per-file work with bounded concurrency to control in-flight load.

## At a glance

- **Best for:** increasing throughput without unbounded request bursts.
- **Input:** directory of files + one prompt.
- **Output:** aggregate success count for a bounded fan-out run.

## Before you run

- Start with low concurrency and increase gradually.
- Keep prompt short and stable during throughput tuning.

## Command

```bash
python -m cookbook optimization/large-scale-batching -- \
  --input cookbook/data/demo/text-medium --limit 8 --concurrency 4 --mock
```

## What to look for

- `ok` count should stay near total file count.
- Higher concurrency should improve throughput until limits are hit.
- Failures at higher concurrency usually signal rate/latency pressure.

## Tuning levers

- `--concurrency` controls client-side in-flight work.
- `--limit` controls batch size and test duration.

## Failure modes

- Aggressive concurrency can trigger transient provider errors.
- Very large files can bottleneck individual workers.
- Mixed workload sizes hide optimal concurrency settings.

## Extend this recipe

- Compare with [Rate Limits and Concurrency](../production/rate-limits-and-concurrency.md).
- Add per-item latency logging for deeper tuning.

