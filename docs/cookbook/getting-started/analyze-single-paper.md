# Analyze Single Paper

The baseline recipe: one source, one prompt, clear output.

## At a glance

- **Best for:** prompt quality checks before batching.
- **Input:** one local file (`pdf/txt/md/png/jpg/jpeg`).
- **Output:** status, answer excerpt, token usage (if provided).

## Command

```bash
python -m cookbook getting-started/analyze-single-paper -- \
  --input path/to/file.pdf
```

Real API mode:

```bash
python -m cookbook getting-started/analyze-single-paper -- \
  --input path/to/file.pdf --no-mock --provider gemini --model gemini-2.5-flash-lite
```

## Expected signal

```text
Single-source baseline
Mode: mock | provider=gemini | model=gemini-2.5-flash-lite
Result
- Status: ok
...
```

## Interpret the result

- `Status: ok` means the run completed cleanly.
- If the answer is generic, tighten task framing in `--prompt`.
- Token count helps estimate cost before scaling.

## Common pitfalls

- Wrong file path -> verify `--input` is a real file.
- Vague prompt -> ask for explicit format (e.g., bullets, table, JSON).
- API setup errors -> run in `--mock` first, then switch to `--no-mock`.

## Try next

- Compare two prompt variants on the same source.
- Move to [Batch Process Files](batch-process-files.md).
