# Extract Media Insights

Extract fast highlights from one media source (image, audio, or video) before scaling up.

## At a glance

- **Best for:** validating multimodal prompts and output expectations.
- **Input:** one local media file (`png/jpg/jpeg/mp4/mov/mp3/...`).
- **Output:** per-prompt excerpts plus token usage (when available).

## Before you run

- Start with one source (faster iteration, easier debugging).
- Keep prompts concrete (objects, attributes, timestamps, quoted text).

## Command

Image:

```bash
python -m cookbook getting-started/extract-media-insights -- \
  --input cookbook/data/demo/multimodal-basic/sample_image.jpg --mock
```

Video:

```bash
python -m cookbook getting-started/extract-media-insights -- \
  --input cookbook/data/demo/multimodal-basic/sample_video.mp4 --mock
```

Audio:

```bash
python -m cookbook getting-started/extract-media-insights -- \
  --input cookbook/data/demo/multimodal-basic/sample_audio.mp3 --mock
```

## What to look for

- Outputs should be specific to the media (not generic filler).
- Video prompts should include timestamps **when visible**.
- Audio prompts should extract quotes **when present**, and say `no quotes` otherwise.

## Tuning levers

- Ask for evidence-labeled bullets when descriptions are vague.
- Reduce prompt count while iterating, then add prompts once outputs are stable.

## Failure modes

- Unsupported path/extension -> pass a real media file.
- Weak grounding -> ask for concrete details (colors, positions, counts, timestamps).
- Provider errors in real mode -> retry in `--mock`, then rerun with `--no-mock`.

## Extend this recipe

- Scale to directories with [Broadcast Process Files](broadcast-process-files.md).
- Increase throughput with [Large-Scale Fan-Out](../optimization/large-scale-fan-out.md).
- For multi-source video synthesis, use [Multi-Video Synthesis](../research-workflows/multi-video-synthesis.md).

