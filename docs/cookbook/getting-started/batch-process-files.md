# Batch Process Files

Process a directory with shared prompts to get your first throughput baseline.

## At a glance

- **Best for:** consistent analysis across many local files.
- **Input:** directory of supported files.
- **Output:** aggregate status, per-answer excerpts, and duration/tokens.

## Before you run

- Keep prompts fixed while validating throughput.
- Start with a small `--limit` before full-dataset runs.

## Command

```bash
python -m cookbook getting-started/batch-process-files -- \
  --input cookbook/data/demo/text-medium --limit 3 --mock
```

Custom prompt set:

```bash
python -m cookbook getting-started/batch-process-files -- \
  --input ./docs --limit 4 --prompt "List 3 takeaways" --prompt "Extract entities"
```

## What to look for

- `Status: ok` with expected file/prompt counts.
- Answer excerpts are differentiated by prompt intent.
- Duration and token totals scale roughly with `files x prompts`.

## Tuning levers

- Increase `--limit` gradually to find practical throughput limits.
- Use repeated `--prompt` flags to keep each question narrowly scoped.

## Failure modes

- Huge prompt sets can produce noisy, unfocused outputs.
- Mixed file quality lowers aggregate output quality.
- Rate limits in real mode -> lower `--limit` and stage runs.

## Extend this recipe

- Pair with [Rate Limits and Concurrency](../production/rate-limits-and-concurrency.md).
- Promote durable workloads to [Resume on Failure](../production/resume-on-failure.md).

