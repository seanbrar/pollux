# Pollux

Multimodal orchestration for LLM APIs.

> You describe what to analyze. Pollux handles source patterns, context caching, and multimodal complexity—so you don't.

[Documentation](https://polluxlib.dev/) ·
[Quickstart](https://polluxlib.dev/quickstart/) ·
[Cookbook](https://polluxlib.dev/cookbook/)

[![PyPI](https://img.shields.io/pypi/v/pollux-ai)](https://pypi.org/project/pollux-ai/)
[![CI](https://github.com/seanbrar/pollux/actions/workflows/ci.yml/badge.svg)](https://github.com/seanbrar/pollux/actions/workflows/ci.yml)
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
# "The key findings are: (1) three source patterns (fan-out, fan-in,
#  broadcast) and (2) context caching for token and cost savings."
```

`run()` returns a `ResultEnvelope` dict — `answers` is a list with one entry per prompt.

To use OpenAI instead: `Config(provider="openai", model="gpt-5-nano")`.

For a full 2-minute walkthrough (install, key setup, success checks), see the
[Quickstart](https://polluxlib.dev/quickstart/).

## Why Pollux?

- **Multimodal-first**: PDFs, images, video, YouTube URLs, and arXiv papers—same API
- **Source patterns**: Fan-out (one source, many prompts), fan-in (many sources, one prompt), and broadcast (many-to-many)
- **Context caching**: Upload once, reuse across prompts—save tokens and money
- **Structured output**: Get typed responses via `Options(response_schema=YourModel)`
- **Built for reliability**: Async execution, automatic retries, concurrency control, and clear error messages with actionable hints

## Installation

```bash
pip install pollux-ai
```

### API Keys

Get a key from [Google AI Studio](https://ai.dev/) or [OpenAI Platform](https://platform.openai.com/api-keys), then:

```bash
# Gemini (recommended starting point — supports context caching)
export GEMINI_API_KEY="your-key-here"

# OpenAI
export OPENAI_API_KEY="your-key-here"
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

### YouTube and arXiv Sources

```python
from pollux import Source

lecture = Source.from_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
paper = Source.from_arxiv("2301.07041")
```

Pass these to `run()` or `run_many()` like any other source — Pollux handles the rest.

### Structured Output

```python
import asyncio

from pydantic import BaseModel

from pollux import Config, Options, Source, run

class Summary(BaseModel):
    title: str
    key_points: list[str]
    sentiment: str

result = asyncio.run(
    run(
        "Summarize this document.",
        source=Source.from_file("report.pdf"),
        config=Config(provider="gemini", model="gemini-2.5-flash-lite"),
        options=Options(response_schema=Summary),
    )
)
parsed = result["structured"]  # Summary instance
print(parsed.key_points)
```

### Configuration

```python
from pollux import Config

config = Config(
    provider="gemini",
    model="gemini-2.5-flash-lite",
    enable_caching=True,  # Gemini-only in v1.0
)
```

See the [Configuration Guide](https://polluxlib.dev/configuration/) for details.

### Provider Differences

Pollux does not force strict feature parity across providers in v1.0.
See the capability matrix: [Provider Capabilities](https://polluxlib.dev/reference/provider-capabilities/).

## Documentation

- [Quickstart](https://polluxlib.dev/quickstart/) — First result in 2 minutes
- [Concepts](https://polluxlib.dev/concepts/) — Mental model for source patterns and caching
- [Sources and Patterns](https://polluxlib.dev/sources-and-patterns/) — Source constructors, run/run_many, ResultEnvelope
- [Configuration](https://polluxlib.dev/configuration/) — Providers, models, retries, caching
- [Caching and Efficiency](https://polluxlib.dev/caching-and-efficiency/) — TTL management, cache warming, cost savings
- [Troubleshooting](https://polluxlib.dev/troubleshooting/) — Common issues and solutions
- [API Reference](https://polluxlib.dev/reference/api/) — Entry points and types
- [Cookbook](https://polluxlib.dev/cookbook/) — Scenario-driven, ready-to-run recipes

## Contributing

See [CONTRIBUTING](https://polluxlib.dev/contributing/) and [TESTING.md](./TESTING.md) for guidelines.

Built during [Google Summer of Code 2025](https://summerofcode.withgoogle.com/) with Google DeepMind. [Learn more](https://polluxlib.dev/#about)

## License

[MIT](LICENSE)
