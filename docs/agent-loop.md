<!-- Intent: The canonical composition tutorial. Teach users how to build a
     complete tool-calling agent loop using Pollux primitives. This is the page
     that solves the "Boolean Trap" — it proves that complex workflows are built
     by composing run() + continue_tool() inside the user's own loop. Do NOT
     introduce conversation mechanics from scratch — link back to that page.
     Assumes the reader understands continue_from, tool calling setup, and
     continue_tool() from the previous page. Register: warm tutorial. -->

# Building an Agent Loop

This is where everything comes together. We're going to build a complete
agent, a program that reasons, calls tools, reads results, and decides what
to do next, using the primitives you've already learned.

By the end of this page, you'll have a working agent loop and a clear
understanding of *why* it's built this way.

!!! info "Boundary"
    **Pollux owns:** executing each turn (sending the prompt, surfacing tool
    calls, carrying conversation state forward via `continue_tool()`).

    **You own:** the loop itself: how many turns to allow, which tools to
    implement, what to do between turns, and when to stop.

## The Complete Agent

Here's a weather agent that answers questions by calling a `get_weather` tool.
Type it out (or paste it) and run it. We'll break it down afterward.

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

Run it. You should see something like:

```
The weather in NYC is 72°F and sunny. In London, it's also 72°F and sunny.
```

The model asked for two tool calls (one for each city), your code executed
them, and the model composed an answer from both results.

## What You Just Built

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
2. Surfacing `tool_calls` in the result envelope.
3. Carrying conversation state forward via `continue_tool()`.
4. Normalizing the response into a stable `ResultEnvelope`.

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

tools.append({
    "name": "search_web",
    "description": "Search the web for information",
    "parameters": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
})
```

The loop itself doesn't change. It already handles any number of tools.

### Using `history` instead of `continue_from`

`continue_from` is convenient when you have the prior result object.
If you need more control (injecting a system message mid-conversation,
trimming old turns), build `history` manually:

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

### Guiding tool use with system instructions

Use `system_instruction` to constrain when and how the model calls tools:

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

### Adding human-in-the-loop approval

Insert an approval step before executing tool calls:

```python
async def agent_with_approval(user_prompt: str) -> str:
    options = Options(tools=tools, tool_choice="auto")
    result = await run(user_prompt, config=config, options=options)

    for turn in range(MAX_TURNS):
        if "tool_calls" not in result:
            return result["answers"][0]

        # Show what the model wants to do
        for tc in result["tool_calls"][0]:
            print(f"  Tool: {tc['name']}({tc['arguments']})")

        approval = input("Execute these tool calls? [y/n] ")
        if approval.lower() != "y":
            return "Agent stopped by user."

        tool_results = execute_tool_calls(result["tool_calls"][0])
        result = await continue_tool(
            continue_from=result,
            tool_results=tool_results,
            config=config,
            options=Options(tools=tools),
        )

    return result["answers"][0]
```

This is a two-line addition to the loop. That's the benefit of owning
the control flow.

## What to Watch For

- **Always set `MAX_TURNS`.** Without a turn limit, a model that repeatedly
  requests tools can loop indefinitely. 5–10 turns covers most agent tasks.
- **Return errors as tool results, don't raise.** If a tool fails, return a
  JSON error message so the model can reason about the failure. Raising an
  exception breaks the loop.
- **`tool_calls` is per-prompt.** `result["tool_calls"]` is a list of
  lists, one per prompt. For `run()` (single prompt), access
  `result["tool_calls"][0]`.
- **The model can request multiple tools in one turn.** The example handles
  this naturally: `execute_tool_calls` iterates over all calls and returns
  a result for each.

---

For production error handling in agent loops (retries, circuit breakers,
partial failures), see [Handling Errors and Recovery](error-handling.md). To
reduce token costs when your agent reuses the same source content across
turns, see [Reducing Costs with Context Caching](caching.md).
