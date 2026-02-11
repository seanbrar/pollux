# Usage Patterns

Core usage patterns for the v1.0 API.

## Use this page when

- You know what you want to analyze but need the right execution shape.
- You are deciding between `run()` and `run_many()`.
- You want a minimal, correct baseline before scaling to cookbook workflows.

## Decision Matrix

| Task | Use | Why | Avoid when |
|---|---|---|---|
| One question, optional source | `run()` | Smallest surface area | You already know you'll ask many prompts |
| Many prompts on shared source(s) | `run_many()` | Better orchestration and reuse | You only need a single answer |
| Typed schema extraction | `run(..., options=Options(response_schema=...))` | Validated structure, less parsing glue | Provider/model lacks structured output support |
| Same prompt template across many files | Cookbook: [Broadcast Process Files](../cookbook/getting-started/broadcast-process-files.md) | Operational file-walking pattern is prebuilt | You only have one or two files |
| Long jobs needing retries/resume | Cookbook: [Resume on Failure](../cookbook/production/resume-on-failure.md) | Durable manifest + failed-only reruns | Workload is tiny and disposable |

Rule of thumb: if prompts or sources are plural, prefer `run_many()`.

## Pattern 1: Single Prompt + Optional Source

```python
import asyncio
from pollux import Config, Source, run

async def main() -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")
    result = await run(
        "What are the main conclusions?",
        source=Source.from_text("Paper: main conclusion is that caching reduces repeat cost."),
        config=config,
    )
    print(result["status"])
    print(result["answers"][0])

asyncio.run(main())
```

## Pattern 2: Multi-Prompt Execution

```python
import asyncio
from pollux import Config, Source, run_many

async def main() -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")
    sources = [
        Source.from_text("Paper A: attention mechanisms"),
        Source.from_text("Paper B: transformer architectures"),
    ]
    prompts = [
        "List 3 key ideas shared across sources.",
        "What would you investigate next?",
    ]

    envelope = await run_many(prompts, sources=sources, config=config)
    print(envelope["status"])
    for i, answer in enumerate(envelope["answers"], 1):
        print(f"Q{i}: {answer}")

asyncio.run(main())
```

## Pattern 3: Structured Output

```python
import asyncio

from pydantic import BaseModel
from pollux import Config, Options, Source, run

class PaperSummary(BaseModel):
    title: str
    findings: list[str]

async def main() -> None:
    config = Config(provider="openai", model="gpt-5-nano")
    options = Options(response_schema=PaperSummary)
    result = await run(
        "Extract structured summary",
        source=Source.from_text("Title: Example paper. Findings: caching saves tokens."),
        config=config,
        options=options,
    )
    print(result["structured"][0])

asyncio.run(main())
```

## Source Constructors

- `Source.from_text(...)`
- `Source.from_file(...)`
- `Source.from_arxiv(...)`
- `Source.from_youtube(...)`
- `Source.from_uri(...)`

## v1.0 Notes

- Conversation continuity (`history`, `continue_from`) is reserved and disabled in v1.0.
- `delivery_mode="deferred"` is reserved and disabled in v1.0.
- Provider support differs by feature. See [Provider Capabilities](../reference/provider-capabilities.md).

## Success check

You should be able to:

- explain why your use case maps to `run()` or `run_many()`
- run one snippet without code changes beyond model/source values
- identify when to switch to cookbook recipes for scale or production constraints

## Output contract

Healthy output:

- Pattern 1: `status=ok`, `len(answers)==1`
- Pattern 2: `status=ok`, `len(answers)==len(prompts)`
- Pattern 3: `structured` exists and has one item matching your schema

Suspicious output:

- empty answers while status reports `ok` repeatedly
- Pattern 2 answer count differs from prompt count
- structured output missing when schema is requested on a capable provider/model

## Next Steps

- [Concepts](../concepts.md) - Mental model behind source patterns and orchestration
- [Token Efficiency](token-efficiency.md) - Cost/latency reasoning for repeated context
- [Caching](caching.md) - Reduce costs with context caching
- [Cookbook](../cookbook/index.md) - Scenario-driven recipes for scale and production
