# Quick Start

Get your first answer in under 2 minutes.

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

## 4. See the Output

```
ok
The key points are: (1) Pollux supports three execution patterns — fan-out
(one source to many prompts), fan-in (many sources to one prompt), and
broadcast (many sources × many prompts); (2) it provides context caching to
avoid re-uploading the same content for repeated prompts.
```

The `status` is `ok` and the answer references details from the source text.
When this works, swap to your real input: `Source.from_file("document.pdf")`.

**What just happened?** Pollux normalized your prompt and source into a
request, planned the API call, executed it, and extracted the answer into a
standard [ResultEnvelope](sources-and-patterns.md#resultenvelope-reference).
Read [Concepts](concepts.md) for the full mental model.
