<!-- Intent: First contact with Pollux. Get the user to a working result as
     fast as possible. Do NOT teach concepts, source patterns, or advanced
     features — those are linked at the end. Assume the reader knows what an
     LLM API is but has never seen Pollux. Register: warm tutorial. -->

# Getting Started

Let's get Pollux running and see your first result.

## 1. Install

```bash
pip install pollux-ai
```

Or download the latest wheel from
[Releases](https://github.com/seanbrar/pollux/releases/latest).

## 2. Set Your API Key

=== "Gemini"

    Get a key from [Google AI Studio](https://ai.dev/), then:

    ```bash
    export GEMINI_API_KEY="your-key-here"
    ```

=== "OpenAI"

    Get a key from [OpenAI Platform](https://platform.openai.com/api-keys), then:

    ```bash
    export OPENAI_API_KEY="your-key-here"
    ```

Not sure which provider? Start with Gemini — it's the original path and
supports context caching out of the box.

## 3. Run

```python
import asyncio
from pollux import Config, Source, run

async def main() -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")
    result = await run(
        "What are the key points?",
        source=Source.from_text(
            "Pollux handles fan-out, fan-in, and broadcast execution patterns. "
            "It can also reuse context through caching."
        ),
        config=config,
    )
    print(result["status"])
    print(result["answers"][0])

asyncio.run(main())
```

If you chose OpenAI, change config to
`Config(provider="openai", model="gpt-5-nano")`.

!!! tip "No API key yet?"
    Use `Config(provider="gemini", model="gemini-2.5-flash-lite", use_mock=True)` to
    run the pipeline locally without network calls. See [Mock Mode](configuration.md#mock-mode).

## 4. See the Output

```
ok
The key points are: (1) Pollux supports three execution patterns — fan-out
(one source to many prompts), fan-in (many sources to one prompt), and
broadcast (many sources × many prompts); (2) it provides context caching to
avoid re-uploading the same content for repeated prompts.
```

That's your first Pollux result. The `status` is `ok` and the answer
references details from the source text. When this works, swap to your real
input: `Source.from_file("document.pdf")`.

!!! info "What just happened?"
    **Pollux owned:** normalizing your prompt and source into a request,
    planning the API call, executing it, and extracting the answer into a
    standard [ResultEnvelope](sending-content.md#resultenvelope-reference).

    **You owned:** writing the prompt, choosing what to analyze, and deciding
    what to do with the result.

    This boundary runs through every part of Pollux. You'll see it called out
    on each page of the docs.

**What's next?** Read [Core Concepts](concepts.md) for the full mental model,
then [Sending Content to Models](sending-content.md) to explore the API.
