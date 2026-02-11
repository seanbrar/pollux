# Caching

Use provider-side caching when you run the same shared context repeatedly. This
can reduce tokens and latency.

## Use this page when

- You ask multiple prompts over the same source set.
- You want to validate whether cache reuse is occurring.
- You need to choose a practical TTL for repeated workloads.

Prerequisites:

- Real API enabled (`GEMINI_API_KEY` or explicit key)
- Provider that supports caching (Gemini in v1.0)

## Minimal example: create and reuse

Run the same prompt set twice. Pollux computes cache identity from model + source content hash.

```python title="cache_min.py"
import asyncio
from pollux import Config, Source, run_many

async def main() -> None:
    config = Config(
        provider="gemini",
        model="gemini-2.5-flash-lite",
        enable_caching=True,
        ttl_seconds=3600,
    )
    prompts = ["Summarize in one sentence.", "List 3 keywords."]
    sources = [Source.from_text("Caching demo: shared context text")]

    first = await run_many(prompts=prompts, sources=sources, config=config)
    second = await run_many(prompts=prompts, sources=sources, config=config)
    print("first:", first["status"])
    print("second:", second["status"])
    print("cache_used (2nd):", second.get("metrics", {}).get("cache_used"))

asyncio.run(main())
```

Expected result:

- Mock mode: both runs print `ok`; cache metrics are synthetic.
- Real API: second run should show `metrics.cache_used=True` when supported.

## Verification tips

- Look for `metrics.cache_used` on the second run.
- Usage counters are provider-dependent.
- Keep prompts/sources stable between runs when comparing warm vs reuse.

## Troubleshooting

- No cache effects: confirm `enable_caching=True` and a caching-capable provider.
- OpenAI: caching is intentionally unsupported in v1.0.
- See [Provider Capabilities](../reference/provider-capabilities.md).

## Success check

You should see:

- both runs return `status=ok`
- second run reports cache reuse when provider supports it
- token/latency behavior is directionally improved or stable in reuse runs

## Output contract

Healthy output:

- first and second runs both print `ok`
- in real Gemini runs, second pass often reports `cache_used=True`
- second pass is typically faster or similar latency for identical inputs

Suspicious output:

- second pass returns `cache_used=False` consistently with stable inputs
- cache behavior changes while prompts/sources/model were unchanged
- repeated provider errors at low request volume

## Next Steps

- [Token Efficiency](token-efficiency.md) - Broader cost model and source-pattern economics
- [Usage Patterns](patterns.md) - Choose `run()` vs `run_many()` correctly
- [Cookbook: Cache Warming and TTL](../cookbook/optimization/cache-warming-and-ttl.md) - Operational recipe
