# Rate Limits and Concurrency

Compare sequential and bounded-concurrency settings on the same workload.

## At a glance

- **Best for:** selecting a safe, performant concurrency level.
- **Input:** same file set evaluated twice.
- **Output:** status + duration comparison for `c=1` vs `c=N`.

## Before you run

- Keep inputs identical across both runs.
- Start with conservative concurrency (`2-4`) in real API mode.

## Command

```bash
python -m cookbook production/rate-limits-and-concurrency -- \
  --input cookbook/data/demo/text-medium --limit 3 --concurrency 4 --mock
```

## What to look for

- Both runs should finish with healthy statuses.
- Bounded run should usually reduce duration versus sequential.
- If bounded run regresses, concurrency is likely too aggressive.

## Tuning levers

- Raise `--concurrency` stepwise until reliability drops.
- Keep prompt/file complexity constant while tuning.

## Failure modes

- Spiky latency can make single-run duration comparisons noisy.
- Rate limit errors imply concurrency should be reduced.
- Heterogeneous inputs can distort tuning conclusions.

## Extend this recipe

- Track median durations over multiple runs.
- Combine with [Resume on Failure](resume-on-failure.md) for robust pipelines.

