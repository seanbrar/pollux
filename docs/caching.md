<!-- Intent: Teach context caching mechanics: the redundant-context problem,
     creating a cache, cache identity, TTL tuning, and when caching pays off.
     Do NOT cover source patterns or structured output in depth — link to those
     pages. Assumes the reader understands run_many() and fan-out workflows.
     Register: conceptual opening → guided applied. -->

# Reducing Costs with Context Caching

Pollux's context caching uploads content once and reuses it across prompts,
turning redundant re-uploads into cheap cache references.

!!! info "Boundary"
    **Pollux owns:** computing cache identity from content hashes, creating
    and reusing cached context on the provider, single-flight deduplication,
    and TTL management.

    **You own:** deciding when caching is worth the overhead, tuning TTL to
    match your reuse window, and keeping prompts and sources stable between
    runs when comparing warm vs reuse behavior.

## The Redundant-Context Problem

Without caching, asking multiple questions about the same content resends it
every time:

```
Question 1: [video tokens] + [question 1] → [answer 1]
Question 2: [video tokens] + [question 2] → [answer 2]
Question 3: [video tokens] + [question 3] → [answer 3]
```

For a 1-hour video (~946,800 tokens), five questions means transmitting
~4.7M input tokens. The video content is identical each time.

With caching:

```
Upload:     [video tokens] → cached
Question 1: [cache ref] + [question 1] → [answer 1]
Question 2: [cache ref] + [question 2] → [answer 2]
Question 3: [cache ref] + [question 3] → [answer 3]
```

Now you transmit the full content once, plus a small cache reference per
question. Savings compound with each additional prompt.

## Quantifying the Savings

```python
def compare_efficiency(video_tokens: int, num_questions: int) -> None:
    """Compare token usage between naive and cached approaches."""
    question_tokens = 50   # Average question length
    answer_tokens = 100    # Average answer length

    # Naive: send full context each time
    naive_total = num_questions * (video_tokens + question_tokens + answer_tokens)

    # Cached: send context once, reference thereafter
    cached_total = video_tokens + num_questions * (question_tokens + answer_tokens)

    savings = naive_total - cached_total
    savings_pct = (savings / naive_total) * 100

    print(f"Questions: {num_questions}")
    print(f"Naive approach: {naive_total:,} tokens")
    print(f"Cached approach: {cached_total:,} tokens")
    print(f"Savings: {savings:,} tokens ({savings_pct:.1f}%)")

# Example: 1-hour video, 10 questions
compare_efficiency(946_800, 10)
# Savings: 8,521,200 tokens (90.0%)
```

More questions on the same content = greater savings.

## Creating a Cache

Use `create_cache()` to upload content to the provider once, then pass the
returned handle to `run()` or `run_many()` via `Options(cache=handle)`:

```python
import asyncio
from pollux import Config, Options, Source, create_cache, run_many

async def main() -> None:
    config = Config(
        provider="gemini",
        model="gemini-2.5-flash-lite",
    )
    sources = [Source.from_text(
        "ACME Corp Q3 2025 earnings: revenue $4.2B (+12% YoY), "
        "operating margin 18.5%, guidance raised for Q4."
    )]

    handle = await create_cache(sources, config=config, ttl_seconds=3600)

    prompts = ["Summarize in one sentence.", "List 3 keywords."]
    first = await run_many(prompts=prompts, config=config, options=Options(cache=handle))
    second = await run_many(prompts=prompts, config=config, options=Options(cache=handle))

    print("first:", first["status"])
    print("second:", second["status"])
    print("cache_used:", second.get("metrics", {}).get("cache_used"))

asyncio.run(main())
```

### Step-by-Step Walkthrough

1. **Call `create_cache()`.** Pass your sources, config, and a TTL. Pollux
   uploads the content to the provider and returns a `CacheHandle`.

2. **Set `ttl_seconds`.** The TTL controls how long the cached content lives on
   the provider. Match it to your reuse window. 3600s (1 hour) is a
   reasonable default for interactive sessions.

3. **Pass the handle via `Options(cache=handle)`.** Each `run()` or `run_many()`
   call that uses this handle references the cached content instead of
   re-uploading it.

4. **Verify with `metrics.cache_used`.** Check
   `result["metrics"]["cache_used"]` on subsequent calls. `True` confirms
   the provider served content from cache rather than re-uploading.

Pollux computes cache identity from model + source content hash. Calls with
the same handle reuse the cached context automatically.

!!! warning "Options restricted when using a cache handle"
    When `Options(cache=handle)` is set, the following fields **cannot** be
    passed alongside it:

    - `system_instruction` — bake it into `create_cache(system_instruction=...)`
      instead.
    - `tools` — bake them into `create_cache(tools=...)` instead (when
      supported).
    - `tool_choice` — remove it when using cached content.
    - `sources` — bake them into `create_cache()` instead.

    Pollux raises `ConfigurationError` immediately if it detects these
    conflicts.  This mirrors a hard constraint in the Gemini API, where
    `cached_content` cannot coexist with `system_instruction`, `tools`, or
    `tool_config` in the same `GenerateContent` request.

## Cache Identity

Cache keys are deterministic: `hash(model + provider + content hashes of sources)`.

This means:

- **Same content, different file paths** → same cache key. Renaming or moving
  a file doesn't invalidate the cache.
- **Different models** → different cache keys. A cache created for
  `gemini-2.5-flash-lite` won't be reused for `gemini-2.5-pro`.
- **Content changes** → new cache key. Editing a source file produces a fresh
  cache entry.

## Single-Flight Protection

When multiple concurrent calls target the same cache key (common in fan-out
workloads), Pollux deduplicates the creation call: only one coroutine performs
the upload, and others await the same result. This eliminates duplicate uploads
without requiring caller-side coordination.

## Verifying Cache Reuse

Check `metrics.cache_used` on subsequent calls:

- `True` — provider confirmed cache hit
- `False` — full upload (first call, or cache expired)

Keep prompts and sources stable between runs when comparing warm vs reuse
behavior. Usage counters are provider-dependent.

## Tuning TTL

Pass `ttl_seconds` to `create_cache()` to control the cache lifetime. The
default is 3600 seconds (1 hour). Tune it to match your expected reuse window:

- **Too short:** the cache expires before you reuse it, wasting the
  warm-up cost.
- **Too long:** cached content lingers unnecessarily. No correctness
  issues, but it consumes provider-side resources.

For interactive workloads where you run a batch and then refine prompts within
the same session, 3600s is a reasonable starting point. For one-shot scripts,
shorter TTLs (300-600s) avoid lingering cache entries.

## When Caching Pays Off

Caching is most effective when:

- **Sources are large:** video, long PDFs, multi-image sets
- **Prompt sets are repeated:** fan-out workflows with 3+ prompts per source
- **Reuse happens within TTL:** default 3600s; tune via `ttl_seconds`

Caching adds overhead for single-prompt, small-source calls. Start without
caching and enable it when you see repeated context in your workload.

## Provider Dependency

Persistent context caching is **Gemini-only**. Calling `create_cache()` with
a provider that lacks `persistent_cache` support raises an actionable error.
See [Provider Capabilities](reference/provider-capabilities.md) for the full
matrix.

---

For the full provider feature matrix and portability guidance, see
[Provider Capabilities](reference/provider-capabilities.md) and
[Writing Portable Code Across Providers](portable-code.md).
