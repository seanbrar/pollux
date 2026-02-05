# Rate Limits and Concurrency

Compare sequential and bounded-concurrency settings on the same workload.

## At a glance

- **Best for:** choosing an initial safe concurrency setting.
- **Input:** same files/prompts, two concurrency profiles.
- **Output:** side-by-side status and duration comparison.

## Command

```bash
python -m cookbook production/rate-limits-and-concurrency -- \
  --input ./docs --limit 3 --concurrency 4
```

## Expected signal

- Sequential and bounded runs both complete.
- Bounded run improves duration without status regressions.
- Results are stable across repeated runs.

## Interpret the result

- If bounded mode is slower, you are likely throttled.
- If both modes are similar, workload may be too small.
- Choose the lowest concurrency that delivers stable gains.

## Common pitfalls

- Tuning from one tiny run.
- Ignoring tier-specific provider limits.
- Changing inputs between comparisons.

## Try next

- Add p95 latency and retry counts to your benchmark log.
- Combine with [Resume on Failure](resume-on-failure.md) for long-running jobs.
