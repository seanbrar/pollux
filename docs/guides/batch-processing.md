# First Batch — Multiple Prompts, Multiple Sources

> Goal: Run a small batch with two prompts against multiple sources and verify the structure of answers.
>
> Prerequisites: Completed [Quickstart](../quickstart.md).

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
        print(f"Q{i}: {a[:120]}…")

asyncio.run(main())
```

Run it:

```bash
python first_batch.py
```

Expected (mock mode):

- `status` is `ok`
- Two answers are present and echo the prompt context

## Tips

- Real API: See [Troubleshooting](troubleshooting.md) for switching between mock and real API modes.
- Sources: Replace `from_text` with `from_file`, `from_url`, or `from_directory`.
- Options: Use `types.make_execution_options(request_concurrency=1)` to tune concurrency.
