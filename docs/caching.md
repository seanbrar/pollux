<!-- Intent: Teach context caching mechanics: the redundant-context problem,
     preparing a cached environment, cache identity, TTL tuning, when caching
     pays off, reading cache hit token counts from output.usage.cached_tokens,
     and the distinction between Pollux-controlled caching and provider-side
     automatic prompt caching. Do NOT cover source patterns or structured output
     in depth — link to those pages. Assumes the reader understands run_many()
     and fan-out workflows. Register: conceptual opening → guided applied. -->

# Reducing Costs with Context Caching

Pollux's context caching uploads content once and reuses it across prompts,
turning redundant re-uploads into cheap cache references. Providers implement
caching differently, and Pollux gives you different levels of control
depending on the provider.

Caching belongs to the **environment**: the stable instructions, sources, and
tools around your interactions. You express a cache preference on an
`Environment`, and Pollux derives cache identity from that environment's
content.

!!! info "Boundary"
    **Pollux owns:** creating and reusing cached context from an
    `Environment` cache preference, provider-managed caching via `cache="auto"`
    / `cache="none"`, cache identity from content hashes, single-flight
    deduplication, the `metrics.cache_used` signal, and surfacing
    provider-reported cache hit counts in `output.usage.cached_tokens`.

    **You own:** deciding when caching is worth the overhead, tuning TTL to
    match your reuse window, and accounting for billing differences by
    provider when interpreting `cached_tokens`.

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

## Three Caching Paths

Pollux exposes caching through the environment's `cache` preference, plus a
third path that exists at the provider level:

- **Persistent caching (Gemini):** Set `cache=CachePolicy(ttl_seconds=...)` on
  an environment. Pollux uploads the environment's sources once, creates a
  provider-side cache, and references it on every interaction over that
  environment.
- **Provider-managed caching (Anthropic):** With `cache="auto"` (the default)
  Pollux lets the provider's automatic prompt caching apply. `cache="none"`
  opts out.
- **Automatic prompt caching (OpenAI, Gemini, OpenRouter):** These providers
  can discount repeated long prefixes on their own. Pollux does not control
  or configure this, but you can benefit from it without doing anything.

`metrics.cache_used` is `True` for the persistent path. To verify provider
automatic prompt caching, check `output.usage.cached_tokens` or provider-native
billing.

## Provider-Managed Caching (Anthropic)

Anthropic currently describes this provider feature as automatic prompt
caching: it caches shared prefixes from the top of the request downward
(system instruction, tools, conversation history, and repeated prompt
context). You do not create a cache object yourself. In Pollux this is the
default; set `cache="none"` on the environment to opt out.

### Cost Mechanics

Unlike persistent caching, Anthropic changes token pricing per request:

- **Cache writes:** +25% (1.25x standard cost)
- **Cache reads:** -90% (0.10x standard cost)

Caching pays off when a prefix is written once and then reused. Without
caching, sending the same prefix twice costs 2.0x. With caching, it costs
1.35x.

### Default Behavior

Because cache writes cost more, Pollux does not treat provider-managed caching
as a blanket default:

- **Single provider call:** Pollux enables it by default.
- **Multi-call fan-out:** Pollux disables it by default.

This is a request-shape rule, not an API-entrypoint rule. `run()` always makes
one provider call, so the default is on. `run_many()` with multiple prompts
makes multiple parallel calls, so the default is off. `run_many(["Q"])` still
makes one provider call, so the default is on there too.

The reason is cost. In a conversation, the write premium lands once and later
turns benefit from cheap cache reads. In a wide fan-out, many identical calls
arrive before the cache is warm, so you pay the write premium repeatedly.

You opt out with the environment's cache preference:

```python
from pollux import Environment

# Disable provider-managed caching for this environment.
environment = Environment(instructions="...", cache="none")
```

Requesting persistent caching (`CachePolicy`) on a provider that does not
support it raises `ConfigurationError`. Pollux does not silently ignore the
request.

### Current Pollux Scope

Pollux currently exposes Anthropic's default ephemeral caching behavior. It
does not expose Anthropic's 1-hour TTL or manual block-level cache breakpoints
in the public API.

## Persistent Caching (Gemini)

For Gemini, prepare an environment with a `CachePolicy`. Pollux uploads the
environment's sources to the provider once, then references the cache on every
`run()` / `run_many()` / `interact()` call over that environment:

```python
import asyncio
from pollux import CachePolicy, Config, Source, prepare_environment, run_many

async def main() -> None:
    config = Config(
        provider="gemini",
        model="gemini-2.5-flash-lite",
    )
    environment = await prepare_environment(
        sources=[Source.from_text(
            "ACME Corp Q3 2025 earnings: revenue $4.2B (+12% YoY), "
            "operating margin 18.5%, guidance raised for Q4."
        )],
        cache=CachePolicy(ttl_seconds=3600),
        config=config,
    )

    prompts = ["Summarize in one sentence.", "List 3 keywords."]
    first = await run_many(prompts, environment=environment, config=config)
    second = await run_many(prompts, environment=environment, config=config)

    print("first:", first.status)
    print("second:", second.status)
    print("cache_used:", second.outputs[0].metrics.cache_used)

asyncio.run(main())
```

### Step-by-Step Walkthrough

1. **Call `prepare_environment()`.** Pass your sources, config, and a cache
   policy. Pollux uploads the content to the provider, creates the cache, and
   returns a reusable `Environment`. If you set `instructions` or `tools`,
   those become part of the cached bundle too.

2. **Set `ttl_seconds` on the `CachePolicy`.** The TTL controls how long the
   cached content lives on the provider. Match it to your reuse window. 3600s
   (1 hour) is a reasonable default for interactive sessions.

3. **Pass the environment via `environment=`.** Each `run()` / `run_many()` /
   `interact()` call over this environment references the cached content
   instead of re-uploading it.

4. **Verify with `metrics.cache_used`.** The example reads it per output
   (`second.outputs[0].metrics.cache_used`); `run()` exposes it directly as
   `output.metrics.cache_used`. `True` confirms the persistent cache was used.

Pollux computes cache identity deterministically. Interactions over the same
environment reuse the cached context automatically, even across separate calls
in the same process.

!!! note "The environment is the cache"
    When an environment carries a `CachePolicy`, its instructions, sources, and
    tools are baked into the cache, so Pollux does not resend them on each
    request. You do not pass them separately. They live on the `Environment`.
    This mirrors a hard constraint in the Gemini API, where `cached_content`
    cannot coexist with `system_instruction`, `tools`, or `tool_config` in the
    same `GenerateContent` request.

!!! tip "Lazy preparation"
    `prepare_environment()` front-loads the upload and cache creation so errors
    surface early. If you would rather defer the work, construct
    `Environment(..., cache=CachePolicy(...))` directly and pass it to a call.
    Pollux creates the cache on first use and reuses it thereafter.

## Cache Identity

For persistent caches, keys are deterministic:
`hash(model + provider + api_key + system_instruction + tools + source identity hashes)`.

This means:

- **Same content, different file paths** → same cache key. Renaming or moving
  a file doesn't invalidate the cache.
- **Different models or providers** → different cache keys. A cache created
  for `gemini-2.5-flash-lite` won't be reused for `gemini-2.5-pro`, and a
  Gemini cache key won't collide with one from another provider.
- **Different API keys** → different cache keys in the same Python process.
  Pollux scopes persistent cache reuse to the provider account that created it.
- **Different baked-in `instructions` or `tools`** → different cache
  keys. Changing the cached behavior contract creates a fresh cache entry.
- **Different Gemini video settings** → different cache keys. Two sources with
  the same content but different clip windows or FPS do not collapse to the
  same cache entry. This applies only to Gemini, where those settings change
  the provider-visible meaning of the source.
- **Content changes** → new cache key. Editing a source file produces a fresh
  cache entry.

## Single-Flight Protection

When multiple concurrent calls target the same persistent cache key (common in
fan-out workloads), Pollux deduplicates the creation call: only one coroutine
performs the upload, and others await the same result. This eliminates
duplicate uploads without requiring caller-side coordination.

## Verifying Cache Reuse

Check `metrics.cache_used` on the result:

- `True`: the persistent cache was used
- `False`: full upload, provider-managed caching, or cache expired

Keep prompts and sources stable between runs when comparing warm vs reuse
behavior. Automatic prompt caching at the provider level can still reduce
costs even when `cache_used` is `False`.

## Observing Cache Hits

`output.usage.cached_tokens` reports how many input tokens were served from
cache. In a fan-out it is summed across all calls on the `OutputCollection`:

```python
# output from any run() call (or collection from run_many())
cached = output.usage.cached_tokens
total_input = output.usage.input_tokens
print(f"{cached:,} / {total_input:,} input tokens served from cache")
```

For a per-call breakdown in a fan-out:

```python
for i, out in enumerate(collection.outputs):
    print(f"  prompt {i}: {out.usage.cached_tokens:,} cached tokens")
```

**Anthropic billing differs from Gemini and OpenAI.** For Gemini and OpenAI,
`cached_tokens` is a subset of `input_tokens`: cache reads are billed at a
discount from the same pool. For Anthropic, `cached_tokens` is additive: the
total billable input is `input_tokens + cached_tokens`.

## Tuning Persistent Cache TTL

Set `ttl_seconds` on the `CachePolicy` to control the persistent cache
lifetime. The default is 3600 seconds (1 hour). Tune it to match your expected
reuse window:

- **Too short:** the cache expires before you reuse it, wasting the
  warm-up cost.
- **Too long:** cached content lingers unnecessarily. No correctness
  issues, but it consumes provider-side resources.

For interactive workloads where you run a prompt set and then refine prompts
within the same session, 3600s is a reasonable starting point. For one-shot
scripts, shorter TTLs (300-600s) avoid lingering cache entries. Anthropic
manages the lifetime of its provider-managed caches on its side.

## When Caching Pays Off

Caching is most effective when:

- **Sources are large:** video, long PDFs, multi-image sets
- **Prompt sets are repeated:** fan-out workflows with 3+ prompts per source
  using persistent caching
- **Conversations are deep:** multi-turn dialogues with large system prompts
  using provider-managed caching
- **Prompt prefixes repeat across calls:** automatic prompt caching at the
  provider level can help even without a Pollux cache

Caching adds overhead for single-prompt, small-source calls. Start without
caching and enable it when you see repeated context in your workload.

## Provider Dependency

Requesting persistent caching (`CachePolicy`) on a provider that lacks support
raises an actionable error. Automatic prompt caching at the provider level is
separate and not gated by Pollux. See
[Provider Capabilities](reference/provider-capabilities.md) for the full
matrix.

---

For the full provider feature matrix and portability guidance, see
[Provider Capabilities](reference/provider-capabilities.md) and
[Writing Portable Code Across Providers](portable-code.md).
