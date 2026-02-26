<!-- Intent: Teach conversation continuity mechanics: continue_from, manual
     history, and tool messages in history. Also cover tool calling setup
     (defining tools, reading tool_calls, continue_tool). Do NOT include the
     complete agent loop — that's on its own page. Assumes the reader
     understands run() and ResultEnvelope. Register: guided applied. -->

# Continuing Conversations Across Turns

You want a model that remembers prior exchanges, or one that calls tools and
reasons over the results. This page covers the conversation mechanics:
carrying context forward, injecting history, and setting up tool calling.

The complete agent loop that brings these pieces together lives on the
next page: [Building an Agent Loop](agent-loop.md).

At the API level, LLMs are stateless. Each call is independent. Multi-turn
conversations work by passing the full conversation history (previous user
messages, assistant responses, and tool results) back to the model with each
new prompt. The model stores nothing between calls; your code carries state
forward. Tool calling extends this: the model can request actions from your
code mid-conversation, and you execute them and feed results back for the
next turn.

!!! info "Boundary"
    **Pollux owns:** delivering tool definitions to the provider, surfacing
    `tool_calls` in the result envelope, carrying conversation state via
    `continue_from`, and translating history formats across providers.

    **You own:** the loop structure, tool implementations, turn limits,
    error handling per turn, deciding when to stop, and persisting history
    across sessions.

## Continuing a Conversation with `continue_from`

Every successful `run()` returns a `ResultEnvelope` containing internal
conversation state. Pass this envelope back into `Options` to
automatically resume the conversation.

```python
import asyncio
from pollux import Config, Options, run

async def chat_loop() -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")

    # Turn 1: Initial query
    print("User: Hello! Please remember my name is Sean.")
    result1 = await run("Hello! Please remember my name is Sean.", config=config)
    print(f"Assistant: {result1['answers'][0]}")

    # Turn 2: Continuing the session
    print("\nUser: What is my name?")
    result2 = await run(
        "What is my name?",
        config=config,
        options=Options(continue_from=result1),  # Picks up where result1 left off
    )
    print(f"Assistant: {result2['answers'][0]}")

asyncio.run(chat_loop())
```

`continue_from` unpacks the initial prompt, the assistant's previous response,
and any tool calls directly into the context payload without requiring manual
dictionary manipulation.

## Using `history` for Manual Control

If you need to inject mid-conversation context, groom old context out to
save tokens, or resume a chat from a database, `continue_from` won't cut it.

Instead, pass an explicit `history` list of dictionaries containing `role`
and `content`:

```python
import asyncio
from pollux import Config, Options, run

async def manual_history_injection() -> None:
    config = Config(provider="openai", model="gpt-5-nano")

    # Imagine this was pulled from a database
    previous_chat = [
        {"role": "user", "content": "What is the capital of France?"},
        {"role": "assistant", "content": "The capital of France is Paris."}
    ]

    # Resume the chat by passing history into Options
    result = await run(
        "And what is its population?",
        config=config,
        options=Options(history=previous_chat),
    )

    print(f"Assistant: {result['answers'][0]}")

asyncio.run(manual_history_injection())
```

Pollux treats the `history` block chronologically *before* the prompt you
provide to `run()`.

## Handling Tool Messages in History

If your conversation includes tool execution (the model asked for data, you
retrieved it, and now you must return it), `history` is how you manually
format tool responses:

```python
history = [
    {"role": "user", "content": "What's the weather in NYC?"},
    {"role": "assistant", "content": "", "tool_calls": [...]},
    # Format your tool response like this:
    {"role": "tool", "tool_call_id": "call_1", "content": '{"temp_f": 72}'},
]

result = await run(
    "Given that weather, what should I wear?",
    config=config,
    options=Options(history=history, tools=[...]),
)
```

## Setting Up Tool Calling

Pollux passes tool definitions to providers and surfaces tool call responses
in the result envelope.

**Defining tools:** pass a list of tool schemas in `Options.tools`:

```python
from pollux import Options

options = Options(
    tools=[
        {
            "name": "get_weather",
            "description": "Get weather for a location",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
            },
        }
    ],
    tool_choice="auto",  # "auto", "required", "none", or {"name": "..."}
)
```

**Reading tool calls:** when the model invokes tools, the result envelope
includes a `tool_calls` field:

```python
result = await run("What's the weather in NYC?", config=config, options=options)

if "tool_calls" in result:
    for call in result["tool_calls"][0]:  # per-prompt list
        print(call["name"], call["arguments"])
```

## Feeding Tool Results Back with `continue_tool()`

When the model requests tool calls, you execute them in your code and feed the
results back for the next turn. `continue_tool()` handles this handoff: it
takes the previous `ResultEnvelope` (which contains the model's tool-call
requests and conversation state) along with your tool-result messages, and
returns the model's next response.

```python
from pollux import continue_tool

# After executing the tool calls from a previous result...
tool_results = [
    {"role": "tool", "tool_call_id": "call_1", "content": '{"temp_f": 72}'},
]

next_result = await continue_tool(
    continue_from=result,       # The ResultEnvelope containing tool_calls
    tool_results=tool_results,  # Your tool outputs
    config=config,
    options=Options(tools=tools),
)
```

`continue_tool()` internally reconstructs the conversation history from the
previous envelope's state, appends your tool results, and calls `run()` to get
the model's next response. The returned `ResultEnvelope` may contain another
round of `tool_calls` (if the model needs more data) or a final text answer.

## What to Watch For

- **`tool_calls` is per-prompt.** `result["tool_calls"]` is a list of
  lists, one per prompt. For `run()` (single prompt), access
  `result["tool_calls"][0]`.
- **Conversation continuity requires one prompt.** Both `history` and
  `continue_from` work with single-prompt `run()` calls, not `run_many()`.
- **Provider differences exist.** Both Gemini and OpenAI support tool calling
  and tool messages in history. See
  [Provider Capabilities](reference/provider-capabilities.md) for details.

---

Now that you understand the conversation mechanics, see
[Building an Agent Loop](agent-loop.md) to put them together into a complete
tool-calling agent. For production error handling in agent loops, see
[Handling Errors and Recovery](error-handling.md).
