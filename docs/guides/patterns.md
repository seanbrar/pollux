# Usage Patterns

Core usage patterns for the v1.0 API.

## Pattern 1: Single Prompt + Optional Source

```python
import asyncio
from pollux import Config, Source, run

async def main() -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")
    result = await run(
        "What are the main conclusions?",
        source=Source.from_file("paper.pdf"),
        config=config,
    )
    print(result["answers"][0])

asyncio.run(main())
```

## Pattern 2: Multi-Prompt Batching

```python
import asyncio
from pollux import Config, Source, batch

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

    envelope = await batch(prompts, sources=sources, config=config)
    print(envelope["status"])
    for i, answer in enumerate(envelope["answers"], 1):
        print(f"Q{i}: {answer}")

asyncio.run(main())
```

## Pattern 3: Structured Output

```python
from pydantic import BaseModel
from pollux import Config, Options, run

class PaperSummary(BaseModel):
    title: str
    findings: list[str]

config = Config(provider="openai", model="gpt-5-nano")
options = Options(response_schema=PaperSummary)

result = await run("Extract structured summary", config=config, options=options)
print(result["structured"][0])
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

## Next Steps

- [Caching](caching.md) - Reduce costs with context caching
- [Configuration](configuration.md) - Core configuration model
- [Troubleshooting](troubleshooting.md) - Common issues and fixes
