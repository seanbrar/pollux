# Rate Limits and Concurrency

Tune `request_concurrency` safely against rate limits.

## At a glance

- **Best for:** selecting a safe, performant per-plan concurrency level.
- **Input:** fixed context set + fixed prompt count, repeated across multiple trials.
- **Output:** ok-rate + median duration comparison for `c=1` vs `c=N`.

## Before you run

- Keep inputs and prompt count identical across comparisons.
- Start with conservative concurrency (`2-4`) in real API mode.
- Use multiple trials; latency is noisy.

## Command

```bash
python -m cookbook production/rate-limits-and-concurrency \
  --input cookbook/data/demo/text-medium --limit 1 \
  --prompts 12 --trials 3 --concurrency 4 --mock
```

## What to look for

- `bounded ok rate` stays at `N / N`.
- `bounded median duration` improves without increasing error rate.
- If the ok-rate drops at higher concurrency, you’re pushing too hard.

## Tuning levers

- Raise `--concurrency` stepwise until reliability drops.
- Increase `--trials` to reduce noise.
- Keep `--limit` and `--prompts` constant while tuning.

## Failure modes

- Spiky latency can make single-run comparisons misleading; rely on medians.
- Rate limit errors imply concurrency should be reduced.
- Too few prompts can hide the effect of concurrency; use `--prompts 12+`.

## Extend this recipe

- Use [Large-Scale Fan-Out](../optimization/large-scale-fan-out.md) for concurrency across files/items.
- Combine with [Resume on Failure](resume-on-failure.md) for robust pipelines.
