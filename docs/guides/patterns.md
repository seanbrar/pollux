# Usage Patterns

Core patterns for working with Pollux, from simple queries to multi-turn conversations.

## Single Source Analysis

The simplest pattern: one prompt, one source.

```python
import asyncio
from pollux import run_simple, types

async def main():
    result = await run_simple(
        "What are the main conclusions?",
        source=types.Source.from_file("paper.pdf"),
    )
    print(result["answers"][0])

asyncio.run(main())
```

Sources can be files, URLs, text, or directories:

```python
types.Source.from_file("document.pdf")
types.Source.from_url("https://youtube.com/watch?v=...")
types.Source.from_text("Raw text content")
types.Source.from_directory("papers/")
```

## Batch Processing

Multiple prompts across multiple sources in a single call.

```python
import asyncio
from pollux import run_batch, types

async def main():
    sources = [
        types.Source.from_text("Paper A: attention mechanisms"),
        types.Source.from_text("Paper B: transformer architectures"),
    ]
    prompts = [
        "List 3 key ideas shared across sources.",
        "What would you investigate next?",
    ]

    envelope = await run_batch(prompts, sources=sources)

    print(envelope["status"])  # "ok"
    for i, answer in enumerate(envelope["answers"], 1):
        print(f"Q{i}: {answer}")

asyncio.run(main())
```

### Tips

- Use `types.make_execution_options(request_concurrency=1)` to control parallelism
- Replace `from_text` with `from_file`, `from_url`, or `from_directory` for real content

## Multi-Turn Conversations

For workflows requiring follow-up questions and context retention.

```python
from pollux import create_executor, types
from pollux.extensions import Conversation

executor = create_executor()
conv = Conversation.start(
    executor,
    sources=[types.Source.from_file("./whitepaper.pdf")],
)

# Ask a single question
conv = await conv.ask("Summarize the abstract in 3 bullets.")
print(conv.state.turns[-1].assistant)
```

### Sequential Questions

```python
from pollux.extensions import PromptSet

conv, answers, _ = await conv.run(
    PromptSet.sequential("Key claims?", "Caveats?")
)
```

### Vectorized Prompts

Run multiple prompts in a single synthetic turn:

```python
conv, answers, _ = await conv.run(
    PromptSet.vectorized("Experiment A?", "Experiment B?", "Experiment C?")
)
```

### History Management

Keep only recent turns to manage context size:

```python
from pollux.extensions import ConversationPolicy

conv = conv.with_policy(ConversationPolicy(keep_last_n=3))
```

### Persistence

Save conversation state across sessions:

```python
from pollux.extensions.conversation_engine import ConversationEngine
from pollux.extensions.conversation_store import JSONStore

store = JSONStore("./conversations.json")
engine = ConversationEngine(executor, store)

exchange = await engine.ask("session-1", "Hello?")
print(exchange.assistant)
```

## Choosing the Right Pattern

| Pattern | Use when... |
|---------|-------------|
| `run_simple` | Single prompt, single source |
| `run_batch` | Multiple prompts or sources, no conversation state |
| `Conversation` | Multi-turn workflows, follow-up questions |
| `ConversationEngine` | Persistent conversations across sessions |

## Next Steps

- [Caching](caching.md) - Reduce costs with context caching
- [Configuration](configuration.md) - Models, tiers, and options
- [Troubleshooting](troubleshooting.md) - Common issues
