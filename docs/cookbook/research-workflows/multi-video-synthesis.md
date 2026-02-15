# Multi-Video Synthesis

Synthesize themes, disagreements, and tradeoffs across multiple video sources
in a single call. Build from single-video prompts to multi-video synthesis.

## Start with One, Then Add More

If you haven't validated your multimodal prompts yet, start with
[Extract Media Insights](../getting-started/extract-media-insights.md) on a
single video. Once prompts are stable, scale here.

## Run It

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

## What You'll See

```
Sources: 2 (video1.mp4, video2.mp4)
Status: ok

Prompt 1 — "Map themes per source":
  Video 1: distributed systems, consensus protocols
  Video 2: eventual consistency, partition tolerance

Prompt 2 — "Highlight disagreements":
  Video 1 advocates strong consistency; Video 2 argues for availability.

Prompt 3 — "Synthesize tradeoffs":
  Both acknowledge the CAP theorem but prioritize differently...
```

Each prompt maps themes per source, highlights genuine disagreements, and
synthesizes tradeoffs — rather than blending everything generically.

## Tuning

- Start with `--max-sources 2` for clarity, then increase.
- Ask for source-labeled bullets to improve traceability.
- Long videos increase latency and cost significantly.

## Next Steps

Combine with [Comparative Analysis](comparative-analysis.md) for structured
diffs across sources.
