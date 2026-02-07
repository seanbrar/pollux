# Extract Image Insights

Extract fast highlights from one image before scaling to bigger pipelines.

## At a glance

- **Best for:** validating image prompts and output expectations.
- **Input:** one local `png/jpg/jpeg`.
- **Output:** per-prompt excerpts plus token usage (when available).

## Before you run

- Start with a single image (faster iteration, easier debugging).
- Keep prompts concrete (objects, attributes, extracted text).

## Command

```bash
python -m cookbook getting-started/extract-image-insights -- \
  --input cookbook/data/demo/multimodal-basic/sample_image.jpg --mock
```

## What to look for

- Prompt 1 should be specific to the scene (not generic “this is an image” filler).
- Prompt 2 should list objects with grounded attributes.
- Prompt 3 should either extract text verbatim or clearly report `no text`.

## Tuning levers

- Ask for evidence-labeled bullets when descriptions are vague.
- Keep prompts short while you’re iterating on multimodal behavior.

## Failure modes

- Unsupported path/extension -> pass a real `png/jpg/jpeg` file.
- Weak grounding -> ask for concrete visual details (colors, positions, counts).
- Provider errors in real mode -> retry in `--mock`, then rerun with `--no-mock`.

## Extend this recipe

- Scale to directories with [Broadcast Process Files](broadcast-process-files.md).
- Increase throughput with [Large-Scale Fan-Out](../optimization/large-scale-fan-out.md).
