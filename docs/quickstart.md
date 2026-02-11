# Quick Start

Get your first answer in under 2 minutes.

## Use this page when

- you want the fastest path to a working Pollux call
- you prefer one happy-path example before exploring alternatives

## 1) Install

```bash
pip install pollux
```

Or download the latest wheel from
[Releases](https://github.com/seanbrar/pollux/releases/latest).

## 2) Choose provider and set your API key

Pollux started as a Gemini-first project and this quickstart defaults to
Gemini. OpenAI is also supported in v1.0.

Provider start guide:

| If you need | Start with | Why |
|---|---|---|
| Context caching or YouTube URL workflows | Gemini (`gemini-2.5-flash-lite`) | Gemini supports provider-side caching and stronger native multimodal breadth in v1.0 |
| JSON-schema extraction with OpenAI models | OpenAI (`gpt-5-nano`) | Structured outputs are supported and easy to validate with `Options(response_schema=...)` |
| Unsure | Gemini first, then compare | Gemini is the original path and usually the fastest way to first success |

See [Provider Capabilities](reference/provider-capabilities.md) before
committing a provider/model choice for production.

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

## 3) Run

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
When this works, switch to your real input with `Source.from_file("document.pdf")`.

Expected result: status + a short answer printed to your terminal.

Success check:

- call completes without exceptions
- output references details from the source text (for example `fan-out` or `caching`)

## Output contract

Healthy output:

- `status` is `ok`
- `answers` contains exactly one string
- answer references the provided source text

Suspicious output:

- empty answer or generic filler unrelated to source text
- repeated failures with `ConfigurationError` (usually key/provider mismatch)
- repeated `status=partial` on this minimal example

## Next Steps

- **[Concepts](concepts.md)** — Mental model for source patterns and context caching
- **[Usage Patterns](guides/patterns.md)** — Single-call and multi-prompt execution patterns
- **[Configuration](guides/configuration.md)** — Providers, models, and options
- **[Provider Capabilities](reference/provider-capabilities.md)** — Provider-specific features and limits
- **[Cookbook](cookbook/index.md)** — Ready-to-run recipes
