# Extract Video Insights

Pull highlights and entities from one video before moving to multi-video synthesis.

## At a glance

- **Best for:** first-pass analysis of one clip.
- **Input:** one `mp4`/`mov` file.
- **Output:** prompt-wise excerpts + usage summary.

## Command

```bash
python -m cookbook getting-started/extract-video-insights -- \
  --input ./clip.mp4
```

## Expected signal

- Prompt 1 returns moments/highlights.
- Prompt 2 returns entities/objects and roles.
- Status is `ok` and output is concise enough for decisions.

## Interpret the result

- Missing timestamps are normal for some sources; ask for event order.
- Weak entity quality usually means prompts need tighter scope.
- Retries are built in for transient provider delays.

## Common pitfalls

- Bad path -> verify `--input` points to a real file.
- Low-value output -> ask for stricter structure in prompt wording.
- Large clips -> start with shorter samples to tune prompts first.

## Try next

- Run multiple clips with [Multi-Video Batch](../research-workflows/multi-video-batch.md).
- Add schema constraints for machine-readable outputs.
