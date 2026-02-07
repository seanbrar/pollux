# Run vs RunMany

Batch prompts with `run_many()` instead of writing a `run()` loop.

## At a glance

- **Best for:** multiple questions about the same source, with minimal orchestration.
- **Input:** one file (`pdf/txt/md/png/jpg/jpeg`).
- **Output:** wall-time + token comparison, plus a sample answer excerpt.

## Before you run

- Start in `--mock` to validate inputs and prompt set.
- Switch to `--no-mock` to observe real provider overhead and upload reuse effects.

## Command

```bash
python -m cookbook optimization/run-vs-run-many -- \
  --input cookbook/data/demo/text-medium/input.txt --mock
```

Real API mode:

```bash
python -m cookbook optimization/run-vs-run-many -- \
  --input path/to/file.pdf --no-mock --provider gemini --model gemini-2.5-flash-lite
```

## What to look for

- `Batched run_many()` returns **one answer per prompt**.
- In real mode, `run_many()` is often faster than a `run()` loop for the same prompt set.
- Token totals should be in the same ballpark; big deltas usually mean prompts/context changed.

## Tuning levers

- Keep prompt count small (3-8) while iterating on prompt quality.
- Use shorter, narrower prompts while you are measuring overhead and throughput.

## Failure modes

- Flat speedup in `--mock` is expected (no real network/upload cost).
- If answers are empty or generic, tighten prompt constraints before scaling prompt sets.
- Provider errors in real mode: retry in `--mock`, then rerun with smaller prompt sets.

## Extend this recipe

- For many files, use [Broadcast Process Files](../getting-started/broadcast-process-files.md).
- For throughput across files, use [Large-Scale Fan-Out](large-scale-fan-out.md).
