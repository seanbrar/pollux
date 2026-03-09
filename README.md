# Pollux

Multimodal orchestration for LLM APIs.

> You describe what to analyze. Pollux handles source patterns, context caching, and multimodal content, so you don't.

[Documentation](https://polluxlib.dev/) ·
[Getting Started](https://polluxlib.dev/getting-started/)

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
        "What are the key findings and their implications?",
        source=Source.from_file("earnings-report.pdf"),
        config=Config(provider="gemini", model="gemini-2.5-flash-lite"),
    )
)
print(result["answers"][0])
# Revenue grew 18% YoY to $4.2B, driven by cloud services. Operating
# margins improved from 29% to 34%. Management's $2B buyback and raised
# guidance signal confidence in sustained growth.
```

`run()` returns a `ResultEnvelope`: `answers` holds one entry per prompt.

To use OpenAI instead: `Config(provider="openai", model="gpt-5-nano")`.
For Anthropic: `Config(provider="anthropic", model="claude-haiku-4-5")`.
For OpenRouter: `Config(provider="openrouter", model="google/gemma-3-27b-it:free")`.

For a full walkthrough (install, key setup, first result), see
[Getting Started](https://polluxlib.dev/getting-started/).

## What Problems Does Pollux Solve?

Say you have a document and ten questions about it. Each API call re-uploads the file, and you're left managing caching, retries, and concurrency yourself. Pollux uploads once, caches the content, fans out your prompts concurrently, and hands back results.

The same `Source` interface handles PDFs, images, video, YouTube URLs, and arXiv papers. No per-format upload code.

Need structured output? Pass a Pydantic model as `response_schema` and get a validated instance alongside the raw text. Switching providers is a one-line change: `provider="gemini"` to `provider="openai"`.

## One Upload, Many Prompts

Got three questions about the same paper? `run_many()` fans them out concurrently:

```python
import asyncio
from pollux import Config, Source, run_many

envelope = asyncio.run(
    run_many(
        ["Summarize the methodology.", "List key findings.", "Identify limitations."],
        sources=[Source.from_file("paper.pdf")],
        config=Config(provider="gemini", model="gemini-2.5-flash-lite"),
    )
)
for answer in envelope["answers"]:
    print(answer)
```

Add more sources and Pollux broadcasts every prompt across every source, uploading each once regardless of how many prompts reference it.

## Where Pollux Ends

Pollux owns content delivery, context caching, and provider translation. Prompt design, workflow orchestration, and what you do with results are yours. See [Core Concepts](https://polluxlib.dev/concepts/) for the full boundary model.

## Installation

```bash
pip install pollux-ai
```

Set your provider's API key:

```bash
export GEMINI_API_KEY="your-key-here"     # or
export OPENAI_API_KEY="your-key-here"     # or
export ANTHROPIC_API_KEY="your-key-here"  # or
export OPENROUTER_API_KEY="your-key-here"
```

Keys from: [Google AI Studio](https://ai.dev/) · [OpenAI](https://platform.openai.com/api-keys) · [Anthropic](https://console.anthropic.com/settings/keys) · [OpenRouter](https://openrouter.ai/keys)

## Documentation

- [Getting Started](https://polluxlib.dev/getting-started/): first result in 2 minutes
- [Core Concepts](https://polluxlib.dev/concepts/): mental model and vocabulary
- [API Reference](https://polluxlib.dev/reference/api/): entry points and types
- [Cookbook](https://polluxlib.dev/reference/cli/): runnable end-to-end recipes

Full docs at [polluxlib.dev](https://polluxlib.dev/).

## Contributing

See [CONTRIBUTING](https://polluxlib.dev/contributing/) and [TESTING.md](./TESTING.md) for guidelines.

Built during [Google Summer of Code 2025](https://summerofcode.withgoogle.com/) with Google DeepMind. [Learn more](https://polluxlib.dev/#about)

## License

[MIT](LICENSE)
