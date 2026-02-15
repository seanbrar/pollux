# Pollux

Multimodal orchestration for LLM APIs.

> You describe what to analyze. Pollux handles source patterns, context caching, and multimodal complexity—so you don't.
>
> Originally built for Gemini during Google Summer of Code 2025. Pollux now
> supports both Gemini and OpenAI with explicit capability differences.

[Documentation](https://seanbrar.github.io/pollux/) ·
[Quickstart](https://seanbrar.github.io/pollux/quickstart/) ·
[Cookbook](./cookbook/)

![CI](https://github.com/seanbrar/pollux/actions/workflows/ci.yml/badge.svg)
[![codecov](https://codecov.io/gh/seanbrar/pollux/graph/badge.svg)](https://codecov.io/gh/seanbrar/pollux)
[![Testing: MTMT](https://img.shields.io/badge/testing-MTMT_v0.1.0-blue)](https://github.com/seanbrar/minimal-tests-maximum-trust)
![Python](https://img.shields.io/badge/Python-3.10%2B-brightgreen)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Quick Start

```python
import asyncio
from pollux import Config, Source, run

result = asyncio.run(
    run(
        "What are the key findings?",
        source=Source.from_text(
            "Pollux supports fan-out, fan-in, and broadcast source patterns. "
            "It also supports context caching for repeated prompts."
        ),
        config=Config(provider="gemini", model="gemini-2.5-flash-lite"),
    )
)
print(result["answers"][0])
```

For a full 2-minute walkthrough (install, key setup, success checks), use
[Quickstart](https://seanbrar.github.io/pollux/quickstart/). For local-file
analysis, swap to `Source.from_file("paper.pdf")`.

## Why Pollux?

- **Multimodal-first**: PDFs, images, videos, YouTube—same API
- **Source patterns**: Fan-out (one source → many prompts), fan-in, and broadcast
- **Context caching**: Upload once, reuse across prompts—save tokens and money
- **Production-ready core**: async execution, explicit capability checks, clear errors

## Installation

```bash
pip install pollux-ai
```

Or download the latest wheel from [Releases](https://github.com/seanbrar/pollux/releases/latest).

### API Key

Get a key from [Google AI Studio](https://ai.dev/), then:

```bash
export GEMINI_API_KEY="your-key-here"
```

## Usage

### Multi-Source Analysis

```python
import asyncio

from pollux import Config, Source, run_many

async def main() -> None:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")
    sources = [
        Source.from_file("paper1.pdf"),
        Source.from_file("paper2.pdf"),
    ]
    prompts = ["Summarize the main argument.", "List key findings."]

    envelope = await run_many(prompts, sources=sources, config=config)
    for answer in envelope["answers"]:
        print(answer)

asyncio.run(main())
```

### Configuration

```python
from pollux import Config

config = Config(
    provider="gemini",
    model="gemini-2.5-flash-lite",
    enable_caching=True,
)
```

See the [Configuration Guide](https://seanbrar.github.io/pollux/configuration/) for details.

### Provider Differences

Pollux does not force strict feature parity across providers in v1.0.
See the capability matrix: [Provider Capabilities](https://seanbrar.github.io/pollux/reference/provider-capabilities/).

## Documentation

- [Quickstart](https://seanbrar.github.io/pollux/quickstart/) — First result in 2 minutes
- [Concepts](https://seanbrar.github.io/pollux/concepts/) — Mental model for source patterns and caching
- [Sources and Patterns](https://seanbrar.github.io/pollux/sources-and-patterns/) — Source constructors, run/run_many, ResultEnvelope
- [Configuration](https://seanbrar.github.io/pollux/configuration/) — Providers, models, retries, caching
- [API Reference](https://seanbrar.github.io/pollux/reference/api/) — Entry points and types
- [Cookbook](./cookbook/) — Scenario-driven, ready-to-run recipes

## Origins

Pollux was developed as part of Google Summer of Code 2025 with Google DeepMind. [Learn more →](https://seanbrar.github.io/pollux/#about)

## Contributing

See [CONTRIBUTING](https://seanbrar.github.io/pollux/contributing/) and [TESTING.md](./TESTING.md) for guidelines.

## License

[MIT](LICENSE)
