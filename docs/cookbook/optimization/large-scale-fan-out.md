# Large-Scale Fan-Out

Fan out per-file work with bounded concurrency. The knob is
`--concurrency` — start low and ramp up until reliability drops.

## Run It

```bash
python -m cookbook optimization/large-scale-fan-out \
  --input cookbook/data/demo/text-medium --limit 8 --concurrency 4 --mock
```

## Ramping Up

Start conservative, then increase:

```bash
# Baseline: sequential
python -m cookbook optimization/large-scale-fan-out \
  --input cookbook/data/demo/text-medium --limit 8 --concurrency 1 --mock

# Double it
python -m cookbook optimization/large-scale-fan-out \
  --input cookbook/data/demo/text-medium --limit 8 --concurrency 4 --mock

# Push further
python -m cookbook optimization/large-scale-fan-out \
  --input cookbook/data/demo/text-medium --limit 8 --concurrency 8 --mock
```

Higher concurrency should improve throughput until provider rate limits are
hit. Failures at higher concurrency usually signal rate or latency pressure.

## What You'll See

```
Concurrency: 4 | Files: 8
Results: 8/8 ok | Wall time: 3.1s
```

The `ok` count should stay near total file count. Watch for drops as you
increase concurrency.

## Next Steps

Compare with [Rate Limits and Concurrency](../production/rate-limits-and-concurrency.md)
for a more rigorous benchmarking approach.
