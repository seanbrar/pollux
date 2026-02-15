# Broadcast Process Files

Once you've validated prompt quality on a single file, broadcast the same
prompts across a directory. This is the "map over files" pattern.

## Run It

The transition from [Analyze Single Paper](analyze-single-paper.md) is
straightforward: swap a file path for a directory, add `--limit` to control
scope.

```bash
python -m cookbook getting-started/broadcast-process-files \
  --input cookbook/data/demo/text-medium --limit 3 --mock
```

Custom prompts:

```bash
python -m cookbook getting-started/broadcast-process-files \
  --input ./docs --limit 4 --prompt "List 3 takeaways" --prompt "Extract entities"
```

## What You'll See

```
File 1/3: input.txt
  Status: ok | Answers: 2 / 2
  Excerpt: "Three main findings: (1) caching reduces..."

File 2/3: compare.txt
  Status: ok | Answers: 2 / 2
  Excerpt: "The comparison methodology uses..."

File 3/3: notes.txt
  Status: ok | Answers: 2 / 2
  Excerpt: "Key entities: Pollux, context caching..."

Summary: 3/3 ok | Total tokens: 4,120 | Wall time: 2.1s
```

Each file prints its status and answer count. Excerpts should be specific to
each file. Total tokens and wall time scale roughly with `files × prompts`.

## Tuning

- Use repeated `--prompt` flags to keep each question narrowly scoped.
- Increase `--limit` gradually once excerpts look consistently correct.
- Huge prompt sets produce noisy output — start with 2-3 prompts.

## Next Steps

Scale throughput with [Large-Scale Fan-Out](../optimization/large-scale-fan-out.md),
or add durability with [Resume on Failure](../production/resume-on-failure.md).
