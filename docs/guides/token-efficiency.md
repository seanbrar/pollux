# Token Efficiency

Pollux helps you get more value from every API call through **context caching** and **source patterns**. This guide explains the underlying economics and how to leverage them.

## Use this page when

- You run repeated prompts on shared context and want to control cost.
- You need to choose between single-call and multi-prompt execution patterns.
- You are tuning workloads before production rollout.

## The Problem: Redundant Context

When you ask multiple questions about the same content, naive approaches send that content repeatedly:

```
Question 1: [video tokens] + [question 1] → [answer 1]
Question 2: [video tokens] + [question 2] → [answer 2]
Question 3: [video tokens] + [question 3] → [answer 3]
```

For a 1-hour video (~946,800 tokens), asking 5 questions means transmitting ~4.7 million input tokens—even though the video content is identical each time.

## The Solution: Context Caching

Pollux uploads content once and caches it for reuse:

```
Upload:     [video tokens] → cached
Question 1: [cache ref] + [question 1] → [answer 1]
Question 2: [cache ref] + [question 2] → [answer 2]
Question 3: [cache ref] + [question 3] → [answer 3]
```

Now you transmit ~946,800 tokens once, plus a small cache reference for each question. The savings compound with each additional question.

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

**The efficiency scales with questions:** More questions on the same content = greater savings.

## Source Patterns

Pollux supports three patterns for multi-prompt/multi-source analysis:

### Fan-Out: One Source → Many Prompts

The most common efficiency pattern. Upload one piece of content, ask many questions.

```python
import asyncio

from pollux import Config, Source, run_many

config = Config(provider="gemini", model="gemini-2.5-flash-lite")
video = Source.from_file("lecture.mp4")

prompts = [
    "Summarize the main argument.",
    "What evidence is presented?",
    "What are the limitations mentioned?",
    "How does this relate to prior work?",
]

envelope = asyncio.run(run_many(prompts, sources=[video], config=config))
```

### Fan-In: Many Sources → One Prompt

Synthesize across multiple sources with a single question.

```python
import asyncio

from pollux import Config, Source, run_many

config = Config(provider="gemini", model="gemini-2.5-flash-lite")
papers = [
    Source.from_file("paper1.pdf"),
    Source.from_file("paper2.pdf"),
    Source.from_file("paper3.pdf"),
]

envelope = asyncio.run(
    run_many(
        ["Compare the methodologies across these papers."],
        sources=papers,
        config=config,
    )
)
```

### Broadcast: Many Sources × Many Prompts

Apply the same analysis template across multiple sources.

```python
import asyncio

from pollux import Config, Source, run_many

config = Config(provider="gemini", model="gemini-2.5-flash-lite")
papers = [Source.from_file(f"paper{i}.pdf") for i in range(1, 6)]
prompts = ["Summarize findings.", "List limitations.", "Rate methodology 1-5."]

envelope = asyncio.run(run_many(prompts, sources=papers, config=config))
# Returns 5 papers × 3 prompts = 15 answers
```

## When to Use `run()` vs `run_many()`

| Scenario | Function | Why |
|----------|----------|-----|
| Quick single question | `run()` | Simpler API |
| Multiple questions, same source | `run_many()` | Fan-out efficiency |
| Same question, multiple sources | `run_many()` | Fan-in analysis |
| Comparative analysis | `run_many()` | Broadcast pattern |

## Best Practices

1. **Group related questions.** If you'll ask 10 questions about the same video, call `run_many()` once, not `run()` ten times.

2. **Keep sources cached.** Pollux manages cache TTLs automatically, but avoid unnecessary re-uploads by reusing `Source` objects.

3. **Mind context limits.** Each provider has maximum context lengths. For very large sources, consider chunking strategies.

4. **Start simple.** Use `run()` for prototyping, then switch to `run_many()` once your prompts are stable.

## Success check

After reading this guide, you should be able to:

- predict when `run_many()` should outperform repeated `run()` calls
- explain why context reuse improves economics for repeated prompts
- choose fan-out, fan-in, or broadcast based on analysis goal

## Further Reading

- [Concepts](../concepts.md) — Mental model for orchestration and tradeoffs
- [Context Caching Guide](caching.md) — TTL management and cache behavior
- [Usage Patterns](patterns.md) — More examples of `run()` and `run_many()`
- [Provider Capabilities](../reference/provider-capabilities.md) — Provider-specific limits and features
- [Cookbook](../cookbook/index.md) — Scenario-driven recipes for throughput and production hardening
