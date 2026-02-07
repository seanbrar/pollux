# Broadcast Process Files

Process a directory by running the same prompt set per file.

## At a glance

- **Best for:** a grokkable "map over files" baseline with consistent prompts.
- **Input:** directory of supported files.
- **Output:** per-file statuses and excerpts, plus a compact end-of-run summary.

## Before you run

- Keep prompts fixed while validating output quality.
- Start with a small `--limit` before full-dataset runs.

## Command

```bash
python -m cookbook getting-started/broadcast-process-files -- \
  --input cookbook/data/demo/text-medium --limit 3 --mock
```

Custom prompt set:

```bash
python -m cookbook getting-started/broadcast-process-files -- \
  --input ./docs --limit 4 --prompt "List 3 takeaways" --prompt "Extract entities"
```

## What to look for

- Each file prints `Status: ok` and `Answers: N / N`.
- Excerpts are specific to each file (not generic boilerplate).
- Total tokens and wall time scale roughly with `files x prompts`.

## Tuning levers

- Use repeated `--prompt` flags to keep each question narrowly scoped.
- Increase `--limit` gradually once excerpts look consistently correct.

## Failure modes

- Huge prompt sets can produce noisy, unfocused outputs.
- Mixed file quality lowers output quality and makes comparisons misleading.
- Rate limits in real mode -> lower `--limit` and stage runs.

## Extend this recipe

- Scale throughput with bounded in-flight calls via [Large-Scale Fan-Out](../optimization/large-scale-fan-out.md).
- Promote durable workloads to [Resume on Failure](../production/resume-on-failure.md).
