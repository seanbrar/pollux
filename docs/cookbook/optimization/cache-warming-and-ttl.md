# Cache Warming and TTL

Measure the impact of context caching by comparing a warm run (first upload)
against a reuse run (cache hit).

## Run It

```bash
python -m cookbook optimization/cache-warming-and-ttl \
  --input cookbook/data/demo/text-medium --limit 2 --ttl 3600 --mock
```

## Warm vs Reuse

The recipe runs the same prompts and sources twice. The first run warms the
cache; the second reuses it.

```
Warm run:
  Status: ok | Tokens: 2,580 | cache_used: false

Reuse run:
  Status: ok | Tokens: 1,200 | cache_used: true

Token delta: -1,380 (53% reduction)
```

Both runs should report `status=ok`. The reuse run should show a cache signal
and lower token usage. If savings are flat, the source may be too small to
benefit from caching.

## Tuning

- Keep files and prompts unchanged between runs for a valid comparison.
- Increase `--limit` to amplify cache economics.
- Tune `--ttl` to match your expected reuse window — too long risks stale
  cache, too short wastes warm-up cost.

## Next Steps

For the economics behind caching, see
[Caching and Efficiency](../../caching-and-efficiency.md). To scale
throughput independently, see
[Large-Scale Fan-Out](large-scale-fan-out.md).
