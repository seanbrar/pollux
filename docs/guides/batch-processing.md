# First Batch - Multiple Prompts, Multiple Sources

Run two prompts across multiple sources and confirm the response shape.

Prerequisite: [Quickstart](../quickstart.md).

## Example

```python
# save as first_batch.py
import asyncio
from pollux import run_batch, types

async def main():
    sources = [
        types.Source.from_text("Paper A: attention is all you need"),
        types.Source.from_text("Video B: transformers explained"),
    ]
    prompts = [
        "List 3 key ideas shared across sources.",
        "What would you investigate next?",
    ]

    envelope = await run_batch(prompts, sources=sources)
    print(envelope["status"])          # expect: "ok"
    print(len(envelope["answers"]))    # expect: 2
    for i, a in enumerate(envelope["answers"], 1):
        print(f"Q{i}: {a[:120]}...")

asyncio.run(main())
```

Run it:

```bash
python first_batch.py
```

Expected result (mock mode):

- `status` is `ok`
- Two answers are present

## Tips

- Real API: See [Troubleshooting](troubleshooting.md) for switching modes.
- Sources: Replace `from_text` with `from_file`, `from_url`, or `from_directory`.
- Options: Use `types.make_execution_options(request_concurrency=1)` to tune concurrency.
