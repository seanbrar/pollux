# Rate Limits and Concurrency

Find the right `request_concurrency` for your workload by benchmarking
sequential vs bounded execution across multiple trials.

## Run It

```bash
python -m cookbook production/rate-limits-and-concurrency \
  --input cookbook/data/demo/text-medium --limit 1 \
  --prompts 12 --trials 3 --concurrency 4 --mock
```

## Reading the Results

```
Sequential (c=1):
  ok rate: 12/12 | median duration: 8.4s

Bounded (c=4):
  ok rate: 12/12 | median duration: 2.6s

Speedup: 3.2x (ok rate held at 100%)
```

The key metric is `ok rate` — it should stay at `N / N` as you increase
concurrency. If the ok-rate drops, you're pushing too hard. Median duration
is more reliable than single-run timing because latency is noisy.

## Tuning

- Raise `--concurrency` stepwise until reliability drops.
- Increase `--trials` to reduce noise in timing comparisons.
- Keep `--limit` and `--prompts` constant while tuning concurrency.
- Start conservative (2-4) in real API mode.

## Next Steps

Use [Large-Scale Fan-Out](../optimization/large-scale-fan-out.md) for
concurrency across files. Combine with
[Resume on Failure](resume-on-failure.md) for robust production pipelines.
