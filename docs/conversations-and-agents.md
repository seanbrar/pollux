# Building Conversations and Agent Loops

You want a model that remembers prior exchanges, or one that calls tools, gets
results, and reasons over them across multiple turns. This page covers both
patterns: multi-turn conversations and tool-calling agent loops.

At the API level, LLMs are stateless — each call is independent. Multi-turn
conversations work by passing the full conversation history (previous user
messages, assistant responses, and tool results) back to the model with each
new prompt. The model itself stores nothing between calls; your code is
responsible for carrying state forward. Tool calling extends this further: the
model can request actions from your code mid-conversation, and you execute
them and feed results back for the next turn.

!!! info "Boundary"
    **Pollux owns:** delivering tool definitions to the provider, surfacing
    `tool_calls` in the result envelope, carrying conversation state via
    `continue_from`, and translating history formats across providers.

    **You own:** the loop structure, tool implementations, turn limits,
    error handling per turn, deciding when to stop, and persisting history
    across sessions.

## Continuing a Conversation with `continue_from`

Every successful `run()` returns a `ResultEnvelope` containing internal
conversation state. Passing this envelope back into `Options` will
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

If you need to inject mid-conversation context, groom old context out to save
tokens, or resume a chat from a database, `continue_from` is insufficient.

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

**Defining tools** — pass a list of tool schemas in `Options.tools`:

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

**Reading tool calls** — when the model invokes tools, the result envelope
includes a `tool_calls` field:

```python
result = await run("What's the weather in NYC?", config=config, options=options)

if "tool_calls" in result:
    for call in result["tool_calls"][0]:  # per-prompt list
        print(call["name"], call["arguments"])
```

## Complete Agent Loop

A weather agent that answers questions by calling a `get_weather` tool,
with a turn limit to prevent runaway loops.

```python
import asyncio
import json

from pollux import Config, Options, run, continue_tool

MAX_TURNS = 5

config = Config(provider="openai", model="gpt-5-nano")

tools = [
    {
        "name": "get_weather",
        "description": "Get current weather for a location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"},
            },
            "required": ["location"],
        },
    }
]

# --- Tool implementations (your code) ---

def get_weather(location: str) -> dict:
    """Stub — replace with a real weather API call."""
    return {"location": location, "temp_f": 72, "condition": "sunny"}


TOOL_DISPATCH = {
    "get_weather": lambda args: get_weather(args["location"]),
}


def execute_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """Run each tool call and return tool-result messages."""
    results = []
    for tc in tool_calls:
        try:
            output = TOOL_DISPATCH[tc["name"]](tc["arguments"])
            content = json.dumps(output)
        except Exception as exc:
            content = json.dumps({"error": str(exc)})
        results.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": content,
        })
    return results


async def agent(user_prompt: str) -> str:
    """Run a tool-calling agent loop and return the final answer."""
    options = Options(tools=tools, tool_choice="auto", history=[])
    result = await run(user_prompt, config=config, options=options)

    for turn in range(MAX_TURNS):
        if "tool_calls" not in result:
            return result["answers"][0]

        # Execute every tool the model requested
        tool_results = execute_tool_calls(result["tool_calls"][0])

        # Next turn — model sees tool results and may call more tools
        result = await continue_tool(
            continue_from=result,
            tool_results=tool_results,
            config=config,
            options=Options(tools=tools),
        )

    return result["answers"][0]  # Best-effort after MAX_TURNS


print(asyncio.run(agent("What's the weather in NYC and London?")))
```

### Step-by-Step Walkthrough

1. **Define tools and dispatch.** Tool schemas go to the provider via
   `Options(tools=...)`. A dispatch map connects tool names to your
   implementations — this is your code, not Pollux's.

2. **First turn.** `run()` sends the prompt with tool definitions. The model
   may return an answer directly, or request tool calls.

3. **Check for tool calls.** If `"tool_calls"` is in the result, the model
   wants your tools. If not, the answer is ready.

4. **Execute and feed back.** Run each tool call through your dispatch map
   and build tool-result messages. Pass the previous result and these messages
   into `continue_tool()` to execute the next turn.

5. **Loop with a guard.** `MAX_TURNS` prevents infinite loops. After the
   limit, return whatever the model last produced.

## Variations

### Multiple tools in one turn

The model can request multiple tool calls in a single response. The example
above handles this naturally — `execute_tool_calls` iterates over all calls
in `result["tool_calls"][0]` and returns a result message for each.

### Using `history` instead of `continue_from`

`continue_from` is convenient when you have the prior result object. If you
need more control over the conversation — for example, injecting a system
message mid-conversation or trimming old turns — build `history` manually:

```python
history = [
    {"role": "user", "content": "What's the weather in NYC?"},
    {"role": "assistant", "content": "", "tool_calls": tool_calls},
    {"role": "tool", "tool_call_id": "call_1", "content": '{"temp_f": 72}'},
]

result = await run(
    "Now summarize.",
    config=config,
    options=Options(tools=tools, history=history),
)
```

### Constraining tool use with system instructions

Use `system_instruction` to guide when and how the model calls tools:

```python
options = Options(
    tools=tools,
    tool_choice="auto",
    system_instruction=(
        "You are a weather assistant. Only call get_weather for cities "
        "the user explicitly mentions. Do not guess locations."
    ),
)
```

## What to Watch For

- **Always set `MAX_TURNS`.** Without a turn limit, a model that repeatedly
  requests tools can loop indefinitely. 5-10 turns covers most agent tasks.
- **Return errors as tool results, don't raise.** If a tool fails, return a
  JSON error message so the model can reason about the failure. Raising an
  exception breaks the loop.
- **`tool_calls` is per-prompt.** `result["tool_calls"]` is a list of lists —
  one list per prompt. For `run()` (single prompt), access `result["tool_calls"][0]`.
- **Conversation continuity requires one prompt.** Both `history` and
  `continue_from` work with single-prompt `run()` calls, not `run_many()`.
- **Provider differences exist.** Both Gemini and OpenAI support tool calling
  and tool messages in history. See
  [Provider Capabilities](reference/provider-capabilities.md) for details.
