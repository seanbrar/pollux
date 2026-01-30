# Caching

Use provider-side caching when you run the same shared context repeatedly. It
can reduce tokens and latency, especially for long sources.

Prerequisites:

- Real API enabled (`GEMINI_API_KEY`, `POLLUX_USE_REAL_API=1`)
- A tier that supports caching, if applicable

## Minimal example: create and reuse

Run the same batch twice with a deterministic cache key.

```python title="cache_min.py"
import asyncio
from pollux import run_batch, types
from pollux.core.execution_options import ExecutionOptions, CacheOptions

async def main() -> None:
    prompts = ["Summarize in one sentence.", "List 3 keywords."]
    sources = [types.Source.from_text("Caching demo: shared context text")]

    opts = ExecutionOptions(
        cache=CacheOptions(deterministic_key="demo.shared.context.v1", ttl_seconds=3600)
    )

    first = await run_batch(prompts=prompts, sources=sources, options=opts)
    second = await run_batch(prompts=prompts, sources=sources, options=opts)
    print("first:", first["status"])
    print("second:", second["status"])

asyncio.run(main())
```

Expected result:

- Mock mode: both runs print `ok` (cache is a no-op).
- Real API: the second run should show cache reuse in metrics when supported.

## Verification tips

- Look for `metrics.cache_application` on the second run.
- Some providers expose `cached_*` usage counters; not all do.

## Troubleshooting

- No cache effects: confirm real API is enabled and the provider supports caching.
- Missing counters: rely on `cache_application` rather than token deltas.
