# Multi-Video Synthesis

Synthesize cross-source themes and disagreements across multiple videos.

## At a glance

- **Best for:** multi-video synthesis in a single call.
- **Input:** video file paths and/or YouTube URLs.
- **Output:** per-prompt synthesis, disagreement signals, cross-video summary.

## Before you run

- Start with `--max-sources 2` for clarity and faster iteration.
- Ensure each source is valid (existing file path or reachable URL).

## Command

Explicit sources:

```bash
python -m cookbook research-workflows/multi-video-synthesis \
  --input ./video1.mp4 ./video2.mp4 --max-sources 2 --mock
```

Auto-pick from a directory:

```bash
python -m cookbook research-workflows/multi-video-synthesis \
  --input cookbook/data/demo/multimodal-basic --max-sources 2 --mock
```

Mixed local + URL:

```bash
python -m cookbook research-workflows/multi-video-synthesis \
  --input "https://youtube.com/watch?v=..." ./video2.mp4 --max-sources 2 --mock
```

## What to look for

- Prompt 1 maps themes per source instead of generic blending.
- Prompt 2 highlights genuine disagreements.
- Prompt 3 synthesizes tradeoffs across all included sources.

## Tuning levers

- Reduce source count if attribution quality drops.
- Ask for source-labeled bullets to improve traceability.

## Failure modes

- Invalid path/URL causes immediate input rejection.
- Too many sources can collapse into shallow synthesis.
- Long videos may increase latency/cost significantly.

## Extend this recipe

- Add source citation constraints and confidence tags.
- Combine with [Comparative Analysis](comparative-analysis.md) for deeper structured diffs.

Tip: build and validate your single-source multimodal prompts first with
[Extract Media Insights](../getting-started/extract-media-insights.md).
