# Cache Warming and TTL

Warm shared context once, then reuse it under a controlled TTL.

## At a glance

- **Best for:** reducing repeated token spend on stable workloads.
- **Input:** fixed file set + fixed prompt set.
- **Output:** warm/reuse status, cache signal, token comparison.

## Before you run

- Keep files and prompts unchanged across both runs.
- Choose a TTL that matches your expected reuse window.

## Command

```bash
python -m cookbook optimization/cache-warming-and-ttl -- \
  --input cookbook/data/demo/text-medium --limit 2 --ttl 3600 --mock
```

## What to look for

- Both warm and reuse runs should report `status=ok`.
- Reuse run should often show cache reuse signals and lower/similar tokens.
- If savings are flat, context may be too small or already cheap.

## Tuning levers

- Increase `--limit` to amplify cache economics.
- Tune `--ttl` to avoid stale cache while preserving reuse wins.

## Failure modes

- Changing prompts/files invalidates direct warm-vs-reuse comparison.
- Overlong TTL can hide when underlying content has drifted.
- Provider metrics differ; treat token deltas as directional.

## Extend this recipe

- Add periodic cache regression checks in CI/staging.
- Pair with [Context Caching Explicit](context-caching-explicit.md) for repeatability tests.

