# Context Caching Explicit

Quantify cache impact with a strict back-to-back comparison.

## At a glance

- **Best for:** proving cache value with concrete before/after numbers.
- **Input:** same directory, same prompts, same run conditions.
- **Output:** warm/reuse statuses, token delta, cache-use indicator.

## Before you run

- Freeze prompts and inputs between runs.
- Use at least two representative files for clearer signals.

## Command

```bash
python -m cookbook optimization/context-caching-explicit -- \
  --input cookbook/data/demo/text-medium --limit 2 --mock
```

## What to look for

- Both runs complete successfully.
- Reuse token count trends lower (or equal) to warm run.
- `cache_used on reuse` confirms cache application.

## Tuning levers

- Increase corpus size to make cache savings more visible.
- Repeat multiple trials and compare median token deltas.

## Failure modes

- Any change in files/prompts invalidates comparison quality.
- Tiny inputs may not show meaningful savings.
- Different providers expose cache metrics differently.

## Extend this recipe

- Add this comparison to performance pre-release checks.
- Pair with [Cache Warming and TTL](cache-warming-and-ttl.md) for policy tuning.

