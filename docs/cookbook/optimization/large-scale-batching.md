# Large-Scale Batching

Increase throughput with bounded client-side concurrency.

## At a glance

- **Best for:** many independent file-level runs.
- **Input:** directory, prompt, limit, concurrency.
- **Output:** aggregate success ratio under bounded fan-out.

## Command

```bash
python -m cookbook optimization/large-scale-batching -- \
  --input ./docs --limit 12 --concurrency 4
```

## Expected signal

- Throughput improves relative to sequential execution.
- Error rates stay controlled at selected concurrency.
- Summary shows expected file count and `ok` ratio.

## Interpret the result

- If failures rise quickly, lower concurrency.
- If gains flatten, you may be rate-limit bound.
- File-size variance can hide true concurrency effects.

## Common pitfalls

- Starting at high concurrency without baseline.
- Ignoring provider tier constraints.
- Comparing runs with different file mixes.

## Try next

- Sweep `--concurrency` and chart success/latency.
- Add resumability via [Resume on Failure](../production/resume-on-failure.md).
