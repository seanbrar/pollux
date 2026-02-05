# Context Caching Explicit

Quantify warm-vs-reuse behavior on the same prompts and inputs.

## At a glance

- **Best for:** validating cache impact with real numbers.
- **Input:** fixed file set and fixed prompt set.
- **Output:** warm/reuse status, token delta, cache-use signal.

## Command

```bash
python -m cookbook optimization/context-caching-explicit -- \
  --input ./docs --limit 2
```

## Expected signal

- Both runs complete successfully.
- Reuse token count is typically lower (or similar).
- `cache_used on reuse` indicates cache application.

## Interpret the result

- Treat token deltas as directional; provider accounting can vary.
- Tiny inputs may show little or no difference.
- Use larger, repeated contexts for clearer savings.

## Common pitfalls

- Changing files/prompts between runs invalidates comparison.
- Over-interpreting one run; repeat with representative inputs.
- Assuming all providers report cached tokens identically.

## Try next

- Pair with [Cache Warming and TTL](cache-warming-and-ttl.md).
- Add a benchmark script for regular cache regression checks.
