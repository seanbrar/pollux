# Cache Warming and TTL

Measure cache impact and pick a sane TTL for reuse.

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
- Reuse run should show a cache reuse signal and lower/similar tokens (directional).
- If savings are flat, the repeated context may be too small or already cheap.

## Tuning levers

- Increase `--limit` to amplify cache economics.
- Tune `--ttl` to avoid stale cache while preserving reuse wins.

## Failure modes

- Changing prompts/files invalidates direct warm-vs-reuse comparison.
- Overlong TTL can hide when underlying content has drifted.
- Provider metrics differ; treat token deltas as directional.

## Extend this recipe

- Add periodic cache regression checks in CI/staging.
- Scale throughput separately (fan-out/concurrency); caching is about repeated context economics.
