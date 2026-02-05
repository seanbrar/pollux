# Multi-Video Batch

Synthesize themes and disagreements across multiple video sources.

## At a glance

- **Best for:** cross-video synthesis in one pass.
- **Input:** local files and/or YouTube URLs.
- **Output:** per-prompt synthesis with cross-source signal.

## Command

Local files:

```bash
python -m cookbook research-workflows/multi-video-batch -- \
  ./video1.mp4 ./video2.mp4 --max-sources 2
```

Mixed local + URL:

```bash
python -m cookbook research-workflows/multi-video-batch -- \
  "https://youtube.com/watch?v=..." ./video2.mp4 --max-sources 2
```

## Expected signal

- Prompt 1 maps themes by source.
- Prompt 2 captures disagreements.
- Prompt 3 produces a compact cross-video synthesis.

## Interpret the result

- If synthesis is vague, reduce source count and tighten prompts.
- If source attribution is weak, require source labels in prompt text.
- Start with `--max-sources 2` and scale up gradually.

## Common pitfalls

- Invalid mixed inputs (bad file path/URL).
- Too many sources for prompt complexity.
- Missing source-level constraints in prompt wording.

## Try next

- Enforce source citations in outputs.
- Pair with [Comparative Analysis](comparative-analysis.md) for deeper diffs.
