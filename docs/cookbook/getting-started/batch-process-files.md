# Batch Process Files

Run a fixed prompt set across many files with one command.

## At a glance

- **Best for:** consistent extraction over a directory.
- **Input:** directory of files + prompt set.
- **Output:** one answer per prompt, plus summary metrics.

## Command

```bash
python -m cookbook getting-started/batch-process-files -- \
  --input ./docs --limit 4
```

Custom prompts:

```bash
python -m cookbook getting-started/batch-process-files -- \
  --input ./docs \
  --prompt "List key risks" \
  --prompt "Summarize decisions"
```

## Expected signal

- `Files processed` matches `--limit`
- Number of answers matches number of prompts
- Status is `ok` for baseline runs

## Interpret the result

- If answers look repetitive, prompts are too broad.
- If token usage spikes, reduce `--limit` or shorten prompts.
- If runtime is high, move to concurrency-focused recipes.

## Common pitfalls

- Empty directory -> ensure files exist under `--input`.
- Prompt drift -> keep prompt wording stable for comparisons.
- Overloading the run -> scale in small increments.

## Try next

- Compare with [Large-Scale Batching](../optimization/large-scale-batching.md).
- Add retry/resume with [Resume on Failure](../production/resume-on-failure.md).
