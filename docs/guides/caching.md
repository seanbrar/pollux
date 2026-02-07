# Caching

Use provider-side caching when you run the same shared context repeatedly. This
can reduce tokens and latency.

Prerequisites:

- Real API enabled (`GEMINI_API_KEY` or explicit key)
- Provider that supports caching (Gemini in v1.0)

## Minimal example: create and reuse

Run the same batch twice. Pollux computes cache identity from model + source content hash.

```python title="cache_min.py"
import asyncio
from pollux import Config, Source, batch

async def main() -> None:
    config = Config(
        provider="gemini",
        model="gemini-2.5-flash-lite",
        enable_caching=True,
        ttl_seconds=3600,
    )
    prompts = ["Summarize in one sentence.", "List 3 keywords."]
    sources = [Source.from_text("Caching demo: shared context text")]

    first = await batch(prompts=prompts, sources=sources, config=config)
    second = await batch(prompts=prompts, sources=sources, config=config)
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

## Troubleshooting

- No cache effects: confirm `enable_caching=True` and a caching-capable provider.
- OpenAI: caching is intentionally unsupported in v1.0.
- See [Provider Capabilities](../reference/provider-capabilities.md).
