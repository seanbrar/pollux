# Pollux

Pollux sends prompts and multimodal sources to several LLM providers through
one small Python interface. It handles uploads, shared context, retries,
provider differences, and normalized results.

## Install

Pollux 2.0 is currently a release candidate:

```bash
pip install --pre --upgrade pollux-ai
```

Set the key for the provider you want to use:

```bash
export GEMINI_API_KEY="your-key-here"     # or
export OPENAI_API_KEY="your-key-here"     # or
export ANTHROPIC_API_KEY="your-key-here"  # or
export OPENROUTER_API_KEY="your-key-here"
```

The local provider does not need a key. Point it at an OpenAI-compatible server
with `base_url` or `POLLUX_LOCAL_BASE_URL`.

## Ask About a File

```python
import asyncio

from pollux import Config, Source, run

result = asyncio.run(
    run(
        "What are the key findings?",
        source=Source.from_file("paper.pdf"),
        config=Config(provider="gemini", model="gemini-2.5-flash-lite"),
    )
)

print(result.text)
```

`run()` returns an `Output`. Alongside `text`, it can contain structured data,
tool calls, reasoning, token usage, completion details, and continuation state.

Changing providers is a configuration change:

```python
Config(provider="openai", model="gpt-5-nano")
Config(provider="anthropic", model="claude-haiku-4-5")
Config(provider="openrouter", model="google/gemma-3-27b-it:free")
Config(provider="local", model="gemma3:4b", base_url="http://localhost:11434/v1")
```

## Ask Several Questions About Shared Context

```python
import asyncio

from pollux import Config, Source, run_many

results = asyncio.run(
    run_many(
        [
            "Summarize the methodology.",
            "List the key findings.",
            "Identify the main limitation.",
        ],
        sources=[Source.from_file("paper.pdf")],
        config=Config(provider="gemini", model="gemini-2.5-flash-lite"),
    )
)

for answer in results.answers:
    print(answer)
```

Every prompt sees the same source set. Pollux reuses uploaded content and runs
the prompts concurrently. To process separate files independently, write the
outer loop in your application and call `run()` or `run_many()` for each file.

## Choose the Smallest Entry Point

| Need | Use |
| --- | --- |
| One answer now | `run()` |
| Several prompts over shared sources | `run_many()` |
| Conversation history or tool calls | `interact()` or `Session` |
| Incremental output | `stream()` |
| Provider-side asynchronous work | `defer()` |

The advanced entry points use the same `Environment`, `Input`, `Output`, and
`OutputCollection` types as the simple path.

## Documentation

- [Getting started](https://polluxlib.dev/next/getting-started/)
- [Sending content](https://polluxlib.dev/next/sending-content/)
- [Structured output](https://polluxlib.dev/next/structured-data/)
- [Conversations, tools, and streaming](https://polluxlib.dev/next/agent-loop/)
- [Deferred work](https://polluxlib.dev/next/submitting-work-for-later-collection/)
- [Provider capabilities](https://polluxlib.dev/next/reference/provider-capabilities/)
- [API reference](https://polluxlib.dev/next/reference/api/)
- [Migrating from 1.x](https://polluxlib.dev/next/migrating-to-v2/)

## Development

```bash
uv sync
just check
```

See [Contributing](https://polluxlib.dev/next/contributing/) for the repository
layout and focused development commands.

## License

[MIT](LICENSE)
