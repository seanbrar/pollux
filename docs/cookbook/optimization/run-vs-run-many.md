# Run vs RunMany

An experiment: how much faster is `run_many()` compared to calling `run()` in
a loop? This recipe runs both approaches on the same input and compares
wall time and token usage.

## Run It

```bash
python -m cookbook optimization/run-vs-run-many \
  --input cookbook/data/demo/text-medium/input.txt --mock
```

Real API:

```bash
python -m cookbook optimization/run-vs-run-many \
  --input path/to/file.pdf --no-mock --provider gemini --model gemini-2.5-flash-lite
```

## What You'll See

```
Sequential run() loop (3 prompts):
  Wall time: 4.2s | Tokens: 3,450

Batched run_many() (3 prompts):
  Wall time: 1.8s | Tokens: 3,420
  Answers: 3 / 3

Speedup: 2.3x
```

In real mode, `run_many()` is typically faster because it shares uploads and
runs prompts concurrently. In `--mock` mode the speedup is flat (no real
network cost) — that's expected.

## Tuning

- Keep prompt count small (3-8) while iterating on quality.
- Use shorter prompts while measuring overhead.
- If answers are empty or generic, tighten prompt constraints before scaling.

## Next Steps

For many files, use
[Broadcast Process Files](../getting-started/broadcast-process-files.md).
For throughput tuning, see
[Large-Scale Fan-Out](large-scale-fan-out.md).
