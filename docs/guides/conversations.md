# Conversation: Advanced Features

Concise examples of production‑ready features in the Conversation extension.

## 1) Context Sources (explicit, validated)

```python
from pollux import create_executor
from pollux.core.types import Source
from pollux.extensions import Conversation

ex = create_executor()
conv = Conversation.start(ex, sources=[
    Source.from_file("./whitepaper.pdf"),
    Source.from_text("Pinned system preamble", identifier="preamble"),
])
```

## 2) Modes: Single, Sequential, Vectorized

```python
from pollux.extensions import PromptSet

# Single (one Q→A turn)
conv, _, _ = await conv.run(PromptSet.single("Summarize the abstract."))

# Sequential (N Q→A turns)
conv, answers, _ = await conv.run(PromptSet.sequential(
    "Key claims?", "Caveats?"
))

# Vectorized (one synthetic turn with combined answers)
conv, answers, _ = await conv.run(PromptSet.vectorized(
    "Experiment A?", "Experiment B?", "Experiment C?"
))
```

## 3) History Windowing (production‑grade context control)

```python
from pollux.extensions import ConversationPolicy

conv = conv.with_policy(ConversationPolicy(keep_last_n=3))
# Only the last 3 turns are included in planning history
```

## 4) Cache Identity & Reuse (deterministic, inspectable)

```python
from dataclasses import replace
from pollux.extensions import ConversationPolicy

# Attach deterministic cache identity (state‑level)
conv = Conversation(
    replace(conv.state,
            cache_key="proj:dataset:v1",
            cache_artifacts=("bootstrap",)),
    conv._Conversation__dict__["_executor"],  # internal; prefer start() in real code
)

# Prefer reuse‑only (provider capability applies)
conv = conv.with_policy(ConversationPolicy(reuse_cache_only=True))

# Best‑effort override to a specific provider cache name
conv = conv.with_policy(ConversationPolicy(execution_cache_name="cachedContents/abc"))
```

## 5) Planner Hints via ExecutionOptions (estimation/result)

```python
policy = ConversationPolicy(
    widen_max_factor=1.25,
    clamp_max_tokens=16000,
    prefer_json_array=True,
)
plan = compile_conversation(conv.state, PromptSet.single("Q"), policy)

# Inspect structured options
opts = plan.options
assert opts.estimation.widen_max_factor == 1.25
assert opts.result.prefer_json_array is True
```

## 6) Persistence & OCC (backend‑friendly)

```python
from pollux.extensions.conversation_store import JSONStore
from pollux.extensions.conversation_engine import ConversationEngine

store = JSONStore("./conversations.json")
engine = ConversationEngine(ex, store)

ex1 = await engine.ask("session-1", "Hello?")  # loads → executes → appends
```

## 7) Metrics & Analytics (research‑grade)

```python
conv, answers, metrics = await conv.run(PromptSet.sequential("Q1", "Q2"))
print(metrics.totals)  # aggregate usage
print(conv.analytics())  # success rate, total tokens, avg length
```

### Notes

- Provider‑neutral: the extension never imports vendor SDKs.
- Single seam: execution flows only through `executor.execute(InitialCommand)`.
- Inspectable: `ConversationPlan.hints` mirrors `ExecutionOptions` for audits.
