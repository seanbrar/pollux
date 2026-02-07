# Analyze Single Paper

Start with one source so you can tune prompt quality before scaling.

## At a glance

- **Best for:** establishing a quality baseline and cost signal.
- **Input:** one local file (`pdf/txt/md/png/jpg/jpeg`).
- **Output:** run status, answer excerpt, and token count (when available).

## Before you run

- Run `make demo-data` for deterministic local input.
- Start in `--mock` to validate paths and prompt structure.

## Command

```bash
python -m cookbook getting-started/analyze-single-paper \
  --input cookbook/data/demo/text-medium/input.txt --mock
```

Real API mode:

```bash
python -m cookbook getting-started/analyze-single-paper \
  --input path/to/file.pdf --no-mock --provider gemini --model gemini-2.5-flash-lite
```

## What to look for

- `Status: ok` confirms the request path is healthy.
- The excerpt should be specific to your source, not generic boilerplate.
- Token usage gives your first cost-per-document estimate.

## Tuning levers

- Use `--prompt` to tighten format requirements (bullets/table/JSON).
- Keep this recipe as a golden baseline before changing models.

## Failure modes

- Bad file path -> verify `--input` points to a readable file.
- Vague output -> make task constraints explicit in the prompt.
- API errors -> retry in `--mock`, then re-enable `--no-mock`.

## Extend this recipe

- Run the same file with two prompt variants and compare precision.
- Move to [Broadcast Process Files](broadcast-process-files.md) once quality is stable.

