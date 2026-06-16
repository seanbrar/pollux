<!-- Intent: The canonical composition tutorial. Teach users how to build a
     complete tool-calling agent loop using Pollux primitives. This is the page
     that solves the "Boolean Trap" and proves that complex workflows are built
     by composing interact() inside the user's own loop. Do NOT
     introduce conversation mechanics from scratch. Link back to that page.
     Assumes the reader understands continuation, tool calling setup, and
     interact() from the previous page. Register: warm tutorial. -->

# Building an Agent Loop

We're going to build a complete agent: a program that reasons, calls tools,
reads results, and decides what to do next. Everything on this page uses
primitives you've already learned.

By the end of this page, you'll have a working agent loop and an
understanding of *why* it's built this way.

!!! info "Boundary"
    **Pollux owns:** executing each turn (sending the prompt, surfacing tool
    calls, carrying conversation state forward via `interact()`).

    **You own:** the loop itself: how many turns to allow, which tools to
    implement, what to do between turns, and when to stop.

## The Complete Agent

Here's a weather agent that answers questions by calling a `get_weather` tool.
Type it out (or paste it) and run it. We'll break it down afterward.

```python
import asyncio

from pollux import (
    Config,
    Environment,
    Input,
    ToolCall,
    ToolDeclaration,
    ToolResult,
    interact,
)

MAX_TURNS = 5

config = Config(provider="openai", model="gpt-5-nano")

tools = [
    ToolDeclaration(
        name="get_weather",
        description="Get current weather for a location",
        parameters={
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"},
            },
            "required": ["location"],
        },
    )
]

# --- Tool implementations (your code) ---

def get_weather(location: str) -> dict:
    """Stub — replace with a real weather API call."""
    return {"location": location, "temp_f": 72, "condition": "sunny"}


TOOL_DISPATCH = {
    "get_weather": lambda args: get_weather(args["location"]),
}


def execute_tool_calls(tool_calls: tuple[ToolCall, ...]) -> list[ToolResult]:
    """Run each tool call and return tool-result messages."""
    results = []
    for tc in tool_calls:
        try:
            # Raises ConfigurationError if the model emitted malformed or non-object JSON.
            args = tc.arguments_dict()
            output = TOOL_DISPATCH[tc.name](args)
            results.append(ToolResult.from_value(call_id=tc.id, value=output))
        except Exception as exc:
            results.append(ToolResult.from_value(
                call_id=tc.id,
                value={"error": str(exc)},
                is_error=True,
            ))
    return results


async def agent(user_prompt: str) -> str:
    """Run a tool-calling agent loop and return the final answer."""
    env = Environment(tools=tools)
    out = await interact(
        env,
        Input(content=user_prompt),
        config=config,
        tool_choice="auto",
    )

    for turn in range(MAX_TURNS):
        if not out.tool_calls:
            return out.text

        # Execute every tool the model requested
        tool_results = execute_tool_calls(out.tool_calls)

        # Next turn: model sees tool results and may call more tools
        out = await interact(
            env,
            Input(continuation=out.continuation, tool_results=tool_results),
            config=config,
        )

    return out.text  # Best-effort after MAX_TURNS


print(asyncio.run(agent("What's the weather in NYC and London?")))
```

Run it. You should see something like:

```
The weather in NYC is 72°F and sunny. In London, it's also 72°F and sunny.
```

The model asked for two tool calls (one for each city), your code executed
them, and the model composed an answer from both results.

## Deconstructing the Loop

Let's take this apart, because the structure matters as much as the code.

### You wrote the loop

Look at the `agent()` function. The `for turn in range(MAX_TURNS)` loop is
**your code**. Pollux doesn't provide this loop, and that's deliberate.
Because you wrote it, you can:

- Change `MAX_TURNS` to 1 for a single-shot tool call, or to 20 for a
  deep research agent.
- Add a `time.sleep()` between turns for rate limiting.
- Insert a user confirmation step ("The model wants to call `delete_file`.
  Allow? [y/n]").
- Log every tool call to a database for audit trails.
- Break out of the loop early based on domain-specific conditions.

None of these would work if the loop were hidden behind a
`sequential_tool_loop=True` flag. Keeping the loop in your code means every
variation is a small edit, not a feature request.

### You wrote the dispatch

The `TOOL_DISPATCH` dict and `execute_tool_calls` function are also your code.
This means you control:

- **What tools exist.** Add or remove entries in the dispatch map.
- **How tools execute.** Call a database, hit an API, read a file. Anything.
- **How errors are handled.** The example returns errors as JSON so the
  model can reason about failures. You could also retry, log, or abort.

### Pollux owned each turn

Within each iteration, Pollux handled:

1. Delivering the prompt and tool definitions to the provider.
2. Surfacing `tool_calls` in the `Output` object.
3. Carrying conversation state forward via `interact()`.
4. Normalizing the response into a stable `Output` model.

The boundary is clean: Pollux executes turns, you decide what happens
*between* them.

## Variations

These are all small modifications to the same loop structure.

### Adding more tools

Add entries to the dispatch map and the tools list:

```python
def search_web(query: str) -> dict:
    """Your search implementation."""
    return {"results": [f"Result for: {query}"]}

TOOL_DISPATCH["search_web"] = lambda args: search_web(args["query"])

tools.append(ToolDeclaration(
    name="search_web",
    description="Search the web for information",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
))
```

The loop itself doesn't change. It already handles any number of tools.

### Using `history` instead of `continuation`

`continuation` is convenient when you have the prior `Output` object.
If you need more control (injecting a system message mid-conversation,
trimming old turns), build `history` manually:

```python
from pollux import Message

history = [
    Message(role="user", content="What's the weather in NYC?"),
    Message(role="assistant", content="", tool_calls=tool_calls),
    Message(role="tool", tool_call_id="call_1", content='{"temp_f": 72}'),
]

out = await interact(
    env,
    Input(content="Now summarize.", history=history),
    config=config,
)
```

### Guiding tool use with system instructions

Use `instructions` to constrain when and how the model calls tools, passed to the `Environment`:

```python
env = Environment(
    tools=tools,
    instructions=(
        "You are a weather assistant. Only call get_weather for cities "
        "the user explicitly mentions. Do not guess locations."
    ),
)
```

### Adding human-in-the-loop approval

Insert an approval step before executing tool calls:

```python
async def agent_with_approval(user_prompt: str) -> str:
    env = Environment(tools=tools)
    out = await interact(
        env,
        Input(content=user_prompt),
        config=config,
        tool_choice="auto",
    )

    for turn in range(MAX_TURNS):
        if not out.tool_calls:
            return out.text

        # Show what the model wants to do
        for tc in out.tool_calls:
            print(f"  Tool: {tc.name}({tc.arguments})")

        approval = input("Execute these tool calls? [y/n] ")
        if approval.lower() != "y":
            return "Agent stopped by user."

        tool_results = execute_tool_calls(out.tool_calls)
        out = await interact(
            env,
            Input(continuation=out.continuation, tool_results=tool_results),
            config=config,
        )

    return out.text
```

This is a two-line addition to the loop. That's the benefit of owning
the control flow.

## What to Watch For

- **Always set `MAX_TURNS`.** Without a turn limit, a model that repeatedly
  requests tools can loop indefinitely. 5–10 turns covers most agent tasks.
- **Return errors as tool results, don't raise.** If a tool fails, return a
  JSON error message so the model can reason about the failure. Raising an
  exception breaks the loop.
- **Use `ToolCall.arguments_dict()` for dispatch.** It accepts object-shaped
  JSON arguments and rejects malformed or non-object arguments with an actionable
  error, instead of silently treating them as `{}`.
- **`tool_calls` is a flat tuple on `Output`.** When using `interact()` or `run()`,
  `out.tool_calls` is a flat tuple of `ToolCall` objects.
- **The model can request multiple tools in one turn.** The example handles
  this naturally: `execute_tool_calls` iterates over all calls and returns
  a result for each.

---

For production error handling in agent loops (retries, circuit breakers,
partial failures), see [Handling Errors and Recovery](error-handling.md). To
reduce token costs when your agent reuses the same source content across
turns, see [Reducing Costs with Context Caching](caching.md).
