# Pollux

Pollux is a developer-first library for efficient, long-context, multimodal Gemini
batch processing.

- Use one API call to analyze many sources with multiple prompts.
- Keep costs predictable with batching, caching, and concurrency controls.
- Stay productive with a clean, minimal API that's easy to reason about.

```python
import asyncio
from pollux import run_simple, types

result = asyncio.run(
    run_simple(
        "What are the key points?",
        source=types.Source.from_file("document.pdf"),
    )
)
print(result["answers"][0])
```

**[Get Started ->](quickstart.md)** | **[Guides ->](guides/installation.md)** |
[Cookbook](https://github.com/seanbrar/gemini-batch-prediction/tree/main/cookbook)
