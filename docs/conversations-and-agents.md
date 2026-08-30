<!-- Intent: Teach conversation continuity mechanics: continuation, manual
     history, and tool messages in history. Also cover tool calling setup
     (defining tools, reading tool_calls, interact). Do NOT include the
     complete agent loop (which is on its own page). Assumes the reader
     understands run() and Output. Register: guided applied. -->

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
    `tool_calls` in the Output model, carrying conversation state via
    `continuation`, and translating history formats across providers.

    **You own:** the loop structure, tool implementations, turn limits,
    error handling per turn, deciding when to stop, and persisting history
    across sessions.

## Continuing a Conversation with `Continuation`

Pass a prior result's `continuation` back into the next
`Input(continuation=...)` to resume the provider-correct conversation. Treat the
value as opaque: serialize it with `to_jsonable()`, restore it with
`Continuation.from_jsonable()`, and otherwise pass it back unchanged. Do not
inspect, edit, merge, or summarize its serialized provider state.

To get a `continuation` for subsequent turns in plain conversational calls, the first turn must opt into conversation tracking by passing `history=[]` (or an empty list/tuple). Without it, Pollux treats the call as stateless and does not build continuation state.

!!! note
    When tool calling is active, Pollux auto-populates continuation state whenever the model returns `tool_calls`, so no explicit `history=[]` is needed. The opt-in requirement only applies to plain conversational calls without tools.

```python
import asyncio
from pollux import Config, Environment, Input, interact

async def chat_loop() -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")
    env = Environment()

    # Turn 1: opt into conversation tracking with history=[]
    print("User: Hello! Please remember my name is Sean.")
    result1 = await interact(
        env,
        Input(content="Hello! Please remember my name is Sean.", history=[]),
        config=config,
    )
    print(f"Assistant: {result1.text}")

    # Turn 2: continue from prior result's continuation
    print("\nUser: What is my name?")
    result2 = await interact(
        env,
        Input(continuation=result1.continuation, content="What is my name?"),
        config=config,
    )
    print(f"Assistant: {result2.text}")

asyncio.run(chat_loop())
```

## Using `history` for Manual Control

If you need to inject mid-conversation context, groom old context out to
save tokens, or resume a chat from a database, a prior `continuation` alone
is not enough.

Instead, pass explicit typed `Message` history:

```python
import asyncio
from pollux import Config, Environment, Input, Message, interact

async def manual_history_injection() -> None:
    config = Config(provider="openai", model="gpt-5-nano")
    env = Environment()

    # Pull from database, wrapped in Message objects
    previous_chat = [
        Message(role="user", content="What is the capital of France?"),
        Message(role="assistant", content="The capital of France is Paris.")
    ]

    # Resume the chat by passing history into Input
    result = await interact(
        env,
        Input(content="And what is its population?", history=previous_chat),
        config=config,
    )

    print(f"Assistant: {result.text}")

asyncio.run(manual_history_injection())
```

Pollux treats the `history` block chronologically *before* the prompt you
provide to `interact()`. This deliberately gives up response IDs and opaque
provider replay state. A successful interaction creates a fresh continuation
for the active provider.

## Persisting Agent Transcripts

For agent frameworks, persist Pollux continuation state separately from your
product transcript:

- Keep the `output.continuation.to_jsonable()` serialization when `output.continuation` is
  present and you want Pollux to continue a provider-correct interaction later.
- Maintain your own user-visible transcript for display, search, audit logs, and
  summarization.
- Capture media-bearing inputs as application records that can be reconstructed
  as `Source` values, or send them as current-turn input. Do not flatten PDFs,
  images, audio, video, or provider-native media parts into replay messages.

### Application-Owned Transcripts

If your application is the source of truth for history because it supports
resume, compaction, truncation, or audit logs, keep that transcript in your own
store and rebuild typed `Message` history for each Pollux turn:

```python
from pollux import Environment, Input, Message, Source, interact

history = [Message.from_openai(message) for message in text_messages]
env = Environment(sources=[Source.from_file("current-report.pdf")])

result = await interact(
    env,
    Input(content="Continue the analysis.", history=history),
    config=config,
)
```

`Message.from_openai()` and `Message.to_openai()` bridge individual portable
text/tool messages. Move OpenAI `system` messages to `Environment.instructions`.
Display reasoning is diagnostic output and should not be copied into transcript
messages.

If you need to resume an older session that included files or images, load
those application records and rebuild `Source.from_file(...)`,
`Source.from_uri(...)`, or another source constructor explicitly. Pollux's
replay messages are for conversation turns, not hidden media transport.

### Portable History Shapes

Portable history consists of non-empty user text, assistant text and/or
normalized `ToolCall` values, and tool messages with the matching
`tool_call_id`. Keep parallel tool results in call order. System messages,
media, reasoning, response IDs, and provider-native state are not portable.

Anthropic extended-thinking tool turns are a special boundary: signed thinking
blocks live only in the untouched continuation. Return pending tool results with
that continuation, then compact at a completed interaction boundary. Groomed
history cannot recreate the signatures Anthropic requires.

## Handling Tool Messages in History

If your conversation includes tool execution (the model asked for data, you
retrieved it, and now you must return it), `history` is how you manually
format tool responses:

```python
from pollux import Input, Message, ToolCall, interact

history = [
    Message(role="user", content="What's the weather in NYC?"),
    Message(role="assistant", content="", tool_calls=(
        ToolCall.from_text(id="call_1", name="get_weather", arguments_text='{"location": "NYC"}'),
    )),
    Message(role="tool", tool_call_id="call_1", content='{"temp_f": 72}'),
]

result = await interact(
    env,
    Input(content="Given that weather, what should I wear?", history=history),
    config=config,
)
```

## Setting Up Tool Calling

Pollux passes function tool definitions to providers and surfaces tool call responses in the output. `Environment.tools` is for Pollux-normalized client/application tools that your code executes. Provider-hosted server tools such as web search or code execution are provider-specific and belong in the `provider_options=` keyword argument.

**Defining tools:** pass `ToolDeclaration` objects in `Environment.tools`:

```python
from pollux import Environment, ToolDeclaration

env = Environment(
    tools=[
        ToolDeclaration(
            name="get_weather",
            description="Get weather for a location",
            parameters={
                "type": "object",
                "properties": {"location": {"type": "string"}},
            },
        )
    ],
)
```

Pollux normalizes tool parameter schemas at the provider boundary. For OpenAI (which defaults to strict mode), `additionalProperties: false` and `required` are injected automatically. For Gemini, unsupported fields like `additionalProperties` are stripped. You can define one schema and use it across all providers without modification.

**Reading tool calls:** when the model invokes tools, the completed `Output` includes a `tool_calls` field:

```python
result = await interact(env, Input("What's the weather in NYC?"), config=config, tool_choice="auto")

if result.tool_calls:
    for call in result.tool_calls:
        print(call.name, call.arguments)
```

## Feeding Tool Results Back with `interact()`

When the model requests tool calls, you execute them in your code and feed the results back for the next turn. `interact()` handles this handoff: it takes the previous `Output`'s `continuation` handle along with your tool results, and returns the model's next response.

```python
from pollux import Input, ToolResult, interact

# After executing the tool calls from a previous result...
tool_results = [
    ToolResult(call_id="call_1", content='{"temp_f": 72}'),
]

next_result = await interact(
    env,
    Input(continuation=result.continuation, tool_results=tool_results),
    config=config,
)
```

`interact()` internally reconstructs the conversation history from the previous continuation, appends your tool results, and calls the provider to get the model's next response. The returned `Output` may contain another round of `tool_calls` or a final text answer.

## What to Watch For

- **`tool_calls` is flat on `Output`.** When using `interact()`, `result.tool_calls`
  is a flat tuple of `ToolCall` objects.
- **Conversation continuity requires one prompt.** `interact()` takes a single
  `Input` turn.
- **Plain conversations need `history=[]` on the first turn.** Without
  `history` or `continuation`, Pollux treats a call as stateless and
  does not produce continuation state. Pass `history=[]` on the first
  turn to enable `continuation` on subsequent turns.
- **Tool-call responses auto-populate continuation.** When a call returns
  tool calls, Pollux builds the `continuation` state automatically, even
  without explicit `history=[]`. This means continuation works for the next
  turn of any tool call, with no opt-in needed.
- **Reasoning is output data unless a provider requires opaque replay.**
  Pollux surfaces reasoning text on `Output.reasoning` for display and
  debugging. Provider-specific signed thinking or reasoning blocks are kept
  inside the opaque continuation only when the provider requires them for valid
  follow-up turns; do not copy display reasoning into future messages.
- **Provider differences exist.** Gemini, OpenAI, and Anthropic support tool
  calling and tool messages in history. OpenRouter supports them on models
  that advertise tool support. See
  [Provider Capabilities](reference/provider-capabilities.md) for details.

## Durable Environment Identity

Use `environment.fingerprint(provider=config.provider)` to bind saved work to
the model-facing instructions, sources, tools, and provider. Compose
`config.model` plus application policy/schema identifiers separately. Cache
preferences intentionally do not affect this identity.

---

Now that you understand the conversation mechanics, see
[Building an Agent Loop](agent-loop.md) to put them together into a complete
tool-calling agent. For production error handling in agent loops, see
[Handling Errors and Recovery](error-handling.md).
