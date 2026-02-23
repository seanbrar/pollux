# Configuration

Pollux uses an explicit `Config` object per call. No global state, no
implicit defaults.

## Config Fields

```python
from pollux import Config

config = Config(
    provider="gemini",
    model="gemini-2.5-flash-lite",
)
```

All fields and their defaults:

| Field | Type | Default | Description |
|---|---|---|---|
| `provider` | `"gemini" \| "openai"` | *(required)* | Provider to use |
| `model` | `str` | *(required)* | Model identifier |
| `api_key` | `str \| None` | `None` | Explicit key; auto-resolved from env if omitted |
| `use_mock` | `bool` | `False` | Use mock provider (no network calls) |
| `enable_caching` | `bool` | `False` | Enable provider-side context caching |
| `ttl_seconds` | `int` | `3600` | Cache time-to-live in seconds |
| `request_concurrency` | `int` | `6` | Max concurrent API calls in multi-prompt execution |
| `retry` | `RetryPolicy` | `RetryPolicy()` | Retry configuration |

## API Key Resolution

If `api_key` is omitted, Pollux resolves it from environment variables:

- Gemini: `GEMINI_API_KEY`
- OpenAI: `OPENAI_API_KEY`

```bash
export GEMINI_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

You can also pass a key directly:

```python
config = Config(provider="openai", model="gpt-5-nano", api_key="sk-...")
```

Pollux auto-loads `.env` files via `python-dotenv`. Create a `.env` in your
project root for local development — but never commit it.

## Mock Mode

Use `use_mock=True` for local development without external API calls:

```python
config = Config(provider="gemini", model="gemini-2.5-flash-lite", use_mock=True)
```

Mock responses echo prompts and return synthetic metrics. Useful for validating
pipeline logic, testing integrations, and CI.

## Performance and Cost Controls

```python
config = Config(
    provider="gemini",
    model="gemini-2.5-flash-lite",
    enable_caching=True,       # Reuse uploaded context (Gemini-only in v1.0)
    ttl_seconds=3600,          # Cache lifetime
    request_concurrency=6,     # Concurrent API calls
)
```

| Need | Direction |
|---|---|
| Fast iteration without API calls | `use_mock=True` |
| Reduce token spend on repeated context | `enable_caching=True` |
| Higher throughput for many prompts/sources | Increase `request_concurrency` |
| Better resilience to transient failures | Customize `retry=RetryPolicy(...)` |

## RetryPolicy

Pollux retries transient provider failures with exponential backoff, full
jitter, and a wall-clock deadline:

```python
from pollux import RetryPolicy

config = Config(
    provider="gemini",
    model="gemini-2.5-flash-lite",
    retry=RetryPolicy(max_attempts=3, initial_delay_s=0.25),
)
```

All `RetryPolicy` fields (defaults shown):

| Field | Default | Description |
|---|---|---|
| `max_attempts` | `2` | Total attempts (including the first call) |
| `initial_delay_s` | `0.5` | Delay before the first retry |
| `backoff_multiplier` | `2.0` | Multiplier applied after each retry |
| `max_delay_s` | `5.0` | Upper bound on any single retry delay |
| `jitter` | `True` | Full jitter to avoid thundering herd |
| `max_elapsed_s` | `15.0` | Wall-clock deadline; `None` to disable |

When a provider returns a `Retry-After` hint, Pollux respects it (whichever
is longer: the computed backoff or the server hint).

## Options

While `Config` establishes the infrastructure requirements for a provider connection, `Options` controls per-prompt inference overrides. This design allows you to dynamically tune how text is generated on a call-by-call basis without needing to tear down or recreate the underlying client connection.

```python
from pollux import Options

options = Options(
    system_instruction="You are a concise analyst.",  # Optional global behavior guide
    temperature=0.7,                  # Generation tuning
    top_p=0.9,                        # Generation tuning
    tools=[{"name": "get_weather"}],  # Native tool calling
    tool_choice="auto",               # Tool calling mode ('auto', 'any', 'none', or dict)
    response_schema=MyPydanticModel,  # Structured output extraction
    reasoning_effort="medium",        # Reserved for future provider support
    delivery_mode="realtime",         # "deferred" reserved for future provider batch APIs
)
```

| Field | Type | Default | Description |
|---|---|---|---|
| `system_instruction` | `str \| None` | `None` | Global system prompt |
| `temperature` | `float \| None` | `None` | Sampling temperature |
| `top_p` | `float \| None` | `None` | Nucleus sampling probability |
| `tools` | `list[dict] \| None` | `None` | JSON schemas for native tools |
| `tool_choice` | `str \| dict \| None` | `None` | Tool execution strategy |
| `response_schema` | `type[BaseModel] \| dict` | `None` | Expected JSON response format |
| `reasoning_effort` | `str \| None` | `None` | Reserved for future o1/o3 support |
| `delivery_mode` | `str` | `"realtime"` | Reserved for future batch delivery |
| `history` | `list[dict] \| None` | `None` | Conversation history; mutually exclusive with `continue_from` |
| `continue_from` | `ResultEnvelope \| None` | `None` | Resume from a prior result; mutually exclusive with `history` |

See [Sources and Patterns](sources-and-patterns.md#structured-output) for
a complete structured output example.

### Conversation Continuity

Pollux supports multi-turn conversations via `history` and `continue_from`.
Both are mutually exclusive — use one per call.

- **`history`**: Pass an explicit list of message dicts. Each item must have
  a string `role` field. Regular messages include `content`; tool messages
  may include `tool_call_id`, `tool_calls`, and other keys.
- **`continue_from`**: Pass a prior `ResultEnvelope` returned by `run()` or
  `run_many()`. Pollux extracts the conversation state automatically.

Conversation continuity requires a provider with conversation support
(currently OpenAI only) and exactly one prompt per call.

### Tool Calling

Pollux passes tool definitions to providers and surfaces tool call responses
in the result envelope.

**Defining tools** — pass a list of tool schemas in `Options.tools`:

```python
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
result = await pollux.run("What's the weather in NYC?", config=cfg, options=options)

if "tool_calls" in result:
    for call in result["tool_calls"][0]:  # per-prompt list
        print(call["name"], call["arguments"])
```

### Tool-Call Loop Pattern

Pollux is a single-turn orchestration layer — it does not execute tools or
manage multi-turn loops. Your code owns the loop:

```python
import asyncio, json
from pollux import Config, Options, run

config = Config(provider="openai", model="gpt-5-nano")
tools = [{"name": "get_weather", "parameters": {"type": "object", "properties": {"location": {"type": "string"}}}}]

async def main():
    # Turn 1: initial request with tools
    result = await run(
        "What's the weather in NYC?",
        config=config,
        options=Options(tools=tools, tool_choice="auto"),
    )

    if "tool_calls" not in result:
        print(result["answers"][0])
        return

    # Extract tool calls from the result
    tool_calls = result["tool_calls"][0]

    # Execute tools (your code)
    tool_results = []
    for tc in tool_calls:
        # ... call your actual tool implementation ...
        output = json.dumps({"temp": 72, "unit": "F"})
        tool_results.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": output,
        })

    # Turn 2: feed tool results back via continue_from
    result2 = await run(
        "Now summarize the weather.",
        config=config,
        options=Options(
            tools=tools,
            continue_from=result,
        ),
    )
    print(result2["answers"][0])

asyncio.run(main())
```

Conversation options are provider-dependent: OpenAI supports
`history`/`continue_from` with tool messages; Gemini conversation
support is not yet available.

## Safety Notes

- `Config` is immutable (`frozen=True`). Create a new instance to change values.
- `Config` validates the provider name on init — unknown providers raise
  `ConfigurationError` immediately rather than failing at call time.
- String representation redacts API keys.
- Missing keys in real mode raise `ConfigurationError` with actionable hints.

## Dev Install (Contributors)

See [Contributing](contributing.md) for full development setup instructions.
