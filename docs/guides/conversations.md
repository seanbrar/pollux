# Conversations (Advanced)

Use the Conversation extension when you want multi-turn workflows with a clean,
inspectable interface. It builds on the same batch pipeline as `run_batch`.

## 1) Start a conversation with sources

```python
from pollux import create_executor, types
from pollux.extensions import Conversation

executor = create_executor()
conv = Conversation.start(
    executor,
    sources=[
        types.Source.from_file("./whitepaper.pdf"),
        types.Source.from_text("Pinned system preamble", identifier="preamble"),
    ],
)
```

## 2) Ask a single question

```python
conv = await conv.ask("Summarize the abstract in 3 bullets.")
```

Expected result: the newest answer is available on `conv.state.turns[-1].assistant`.

## 3) Multiple turns (sequential)

```python
from pollux.extensions import PromptSet

conv, answers, _ = await conv.run(
    PromptSet.sequential("Key claims?", "Caveats?")
)
```

## 4) Vectorized prompts (one synthetic turn)

```python
conv, answers, _ = await conv.run(
    PromptSet.vectorized("Experiment A?", "Experiment B?", "Experiment C?")
)
```

## 5) History windowing (keep recent turns only)

```python
from pollux.extensions import ConversationPolicy

conv = conv.with_policy(ConversationPolicy(keep_last_n=3))
```

## 6) Persistence with a store

```python
from pollux.extensions.conversation_engine import ConversationEngine
from pollux.extensions.conversation_store import JSONStore

store = JSONStore("./conversations.json")
engine = ConversationEngine(executor, store)

exchange = await engine.ask("session-1", "Hello?")
print(exchange.assistant)
```

## 7) Metrics & analytics

```python
conv, answers, metrics = await conv.run(PromptSet.sequential("Q1", "Q2"))
print(metrics.totals)
print(conv.analytics())
```

### Notes

- The extension is provider-neutral and uses the same execution pipeline.
- `PromptSet` controls execution mode: single, sequential, or vectorized.
