# Pollux

Efficient multimodal analysis on Google's Gemini API.

> You describe what to analyze. Pollux handles batching, caching, rate limits, and retries—so you don't.

[Documentation](https://seanbrar.github.io/gemini-batch-prediction/) ·
[Quickstart](https://seanbrar.github.io/gemini-batch-prediction/quickstart/) ·
[Cookbook](./cookbook/)

![CI](https://github.com/seanbrar/gemini-batch-prediction/actions/workflows/ci.yml/badge.svg)
[![codecov](https://codecov.io/gh/seanbrar/gemini-batch-prediction/graph/badge.svg)](https://codecov.io/gh/seanbrar/gemini-batch-prediction)
[![Testing: MTMT](https://img.shields.io/badge/testing-MTMT_v0.1.0-blue)](https://github.com/seanbrar/minimal-tests-maximum-trust)
![Python](https://img.shields.io/badge/Python-3.13+-brightgreen)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Quick Start

```python
import asyncio
from pollux import run_simple, types

async def main():
    result = await run_simple(
        "What are the key findings?",
        source=types.Source.from_file("paper.pdf"),
    )
    print(result["answers"][0])

asyncio.run(main())
```

## Why Pollux?

- **Multimodal-first**: PDFs, images, videos, YouTube—same API
- **Intelligent batching**: Fan-out across prompts and sources efficiently
- **Context caching**: Reuse uploaded content, save tokens and money
- **Production-ready**: Rate limiting, retries, async pipelines

## Installation

```bash
pip install pollux
```

Or download the latest wheel from [Releases](https://github.com/seanbrar/gemini-batch-prediction/releases/latest).

### API Key

Get a key from [Google AI Studio](https://ai.dev/), then:

```bash
export GEMINI_API_KEY="your-key-here"
```

### Verify Setup

```bash
pollux-config doctor
```

## Usage

### Batch Processing

```python
from pollux import run_batch, types

sources = [
    types.Source.from_file("paper1.pdf"),
    types.Source.from_file("paper2.pdf"),
]
prompts = ["Summarize the main argument.", "List key findings."]

envelope = await run_batch(prompts, sources=sources)
for answer in envelope["answers"]:
    print(answer)
```

### Configuration

```python
from pollux import create_executor
from pollux.config import resolve_config

config = resolve_config(overrides={
    "model": "gemini-2.0-flash",
    "tier": "tier_1",
    "enable_caching": True,
})

executor = create_executor(config)
```

See the [Configuration Guide](https://seanbrar.github.io/gemini-batch-prediction/guides/configuration/) for details.

## Documentation

- [Quickstart](https://seanbrar.github.io/gemini-batch-prediction/quickstart/) — First result in 2 minutes
- [Guides](https://seanbrar.github.io/gemini-batch-prediction/guides/installation/) — Installation, configuration, patterns
- [API Reference](https://seanbrar.github.io/gemini-batch-prediction/reference/api/) — Entry points and types
- [Cookbook](./cookbook/) — 11 ready-to-run recipes

## Origins

Pollux was developed as part of Google Summer of Code 2025 with Google DeepMind. [Learn more →](https://seanbrar.github.io/gemini-batch-prediction/about/)

## Contributing

See [CONTRIBUTING](https://seanbrar.github.io/gemini-batch-prediction/contributing/) and [TESTING.md](./TESTING.md) for guidelines.

## License

[MIT](LICENSE)
