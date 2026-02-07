# Extract Video Insights

Extract fast highlights from one video before multi-video synthesis.

## At a glance

- **Best for:** validating video prompts and output structure.
- **Input:** one local `mp4`/`mov`.
- **Output:** per-prompt excerpts and token usage.

## Before you run

- Use a short clip first (faster feedback, easier debugging).
- Keep prompts concrete (moments, entities, timestamps).

## Command

```bash
python -m cookbook getting-started/extract-video-insights -- \
  --input cookbook/data/demo/multimodal-basic/sample_video.mp4 --mock
```

## What to look for

- Prompt 1 should identify moments, ideally time-anchored.
- Prompt 2 should call out entities/objects with clear roles.
- Output should be specific to observed scenes, not generic summaries.

## Tuning levers

- Refine prompt verbs (`identify`, `compare`, `justify`) for sharper outputs.
- Keep source clips short while iterating on prompt design.

## Failure modes

- Unsupported path or extension -> pass a real `mp4`/`mov` file.
- Weak source attribution -> ask for per-moment evidence in prompt text.
- Unstable network/provider responses -> rely on built-in retry behavior.

## Extend this recipe

- Scale to [Multi-Video Synthesis](../research-workflows/multi-video-synthesis.md).
- Add schema constraints with [Custom Schema Template](../templates.md).

