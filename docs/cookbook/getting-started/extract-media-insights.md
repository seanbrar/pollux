# Extract Media Insights

Validate multimodal prompts on a single media source — image, audio, or
video — before scaling up.

## Run It

Image:

```bash
python -m cookbook getting-started/extract-media-insights \
  --input cookbook/data/demo/multimodal-basic/sample_image.jpg --mock
```

Video:

```bash
python -m cookbook getting-started/extract-media-insights \
  --input cookbook/data/demo/multimodal-basic/sample_video.mp4 --mock
```

Audio:

```bash
python -m cookbook getting-started/extract-media-insights \
  --input cookbook/data/demo/multimodal-basic/sample_audio.mp3 --mock
```

## What You'll See

```
Source: sample_image.jpg (image/jpeg)
Status: ok

Prompt 1 — "Describe the main subject":
  "A bar chart showing quarterly revenue growth, with Q3 highlighted in blue.
   The y-axis ranges from $0 to $50M."

Prompt 2 — "List all visible text":
  "Title: 'Revenue by Quarter'. Labels: Q1, Q2, Q3, Q4. Values: $12M, $28M,
   $45M, $31M."

Tokens: 890 (prompt: 780 / completion: 110)
```

Outputs should be specific to the media content. Video prompts should include
timestamps when visible; audio prompts should extract quotes when present.

## Tuning

- Keep prompts concrete: ask for objects, attributes, timestamps, quoted text.
- Ask for evidence-labeled bullets when descriptions are vague.
- Reduce prompt count while iterating, then add prompts once outputs stabilize.

## Next Steps

Scale to directories with
[Broadcast Process Files](broadcast-process-files.md), or synthesize across
multiple videos with
[Multi-Video Synthesis](../research-workflows/multi-video-synthesis.md).
