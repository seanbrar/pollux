# Analyze Single Paper

Start with one source so you can tune prompt quality before scaling.

The goal is a quality baseline: one file, one prompt, one answer you can
inspect manually. Get this right first — everything else builds on it.

## Run It

```bash
python -m cookbook getting-started/analyze-single-paper \
  --input cookbook/data/demo/text-medium/input.txt --mock
```

With a real API:

```bash
python -m cookbook getting-started/analyze-single-paper \
  --input path/to/file.pdf --no-mock --provider gemini --model gemini-2.5-flash-lite
```

## What You'll See

```
Status: ok
Answer (excerpt): The paper presents three main findings: (1) context caching
reduces repeated token cost by 85-92%, (2) fan-out patterns benefit most from
caching, and (3) broadcast execution scales linearly with source count...

Tokens: 1,340 (prompt: 1,250 / completion: 90)
```

`Status: ok` means the request path is healthy. The excerpt should be specific
to your source — not generic boilerplate. Token usage gives your first
cost-per-document estimate.

## Tuning

- Use `--prompt` to tighten format requirements (bullets, table, JSON).
- Keep this recipe as a golden baseline before changing models or scaling.
- If the output is vague, make task constraints explicit in the prompt.

## Next Steps

Once your single-source output looks good, scale to multiple files with
[Broadcast Process Files](broadcast-process-files.md).
