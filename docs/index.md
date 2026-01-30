# Pollux

Batch prediction for Gemini. Fewer API calls, lower costs.

```python
from pollux import run_simple, types
import asyncio

result = asyncio.run(run_simple(
    "What are the key points?",
    source=types.Source.from_file("document.pdf"),
))
print(result["answers"][0])
```

**[Get Started →](quickstart.md)** | [Cookbook](https://github.com/seanbrar/gemini-batch-prediction/tree/main/cookbook)
