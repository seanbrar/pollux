# Source Handling — How‑To

Audience: developers assembling sources for batch/question answering. Quadrant: How‑To (goal‑oriented).

Goal: Build `types.Source` objects from files/URIs/text and run combined or per‑source analysis using the frontdoor helpers.

Applies to: `pollux.types.Source`, `frontdoor.run_batch`, `frontdoor.run_parallel`, and `types.sources_from_directory`.

Last reviewed: 2025-09

## 1) Create Sources

```python
from pollux import types

# Text
text_src = types.Source.from_text("Your text content here")

# Single file
file_src = types.Source.from_file("document.pdf")

# YouTube URL (passed as a provider URI)
yt_src = types.Source.from_youtube("https://youtube.com/watch?v=dQw4w9WgXcQ")

# arXiv id or URL (normalized to canonical PDF URL)
arxiv_src = types.Source.from_arxiv("1706.03762")

# Directory expansion helper (explicit)
dir_sources = types.sources_from_directory("path/to/documents/")
```

## 2) Combined analysis (shared context)

Analyze multiple prompts over multiple sources in one vectorized request with shared context using `run_batch`:

```python
import asyncio
from pollux import types
from pollux.frontdoor import run_batch

async def main() -> None:
    sources = [
        types.Source.from_text("Direct text content"),
        types.Source.from_file("document.pdf"),
        types.Source.from_youtube("https://youtu.be/abc123"),
    ]
    prompts = [
        "What are the main topics?",
        "Compare approaches across all sources.",
    ]
    env = await run_batch(prompts, sources=sources)
    print(env["status"], len(env["answers"]))

asyncio.run(main())
```

Verification

- Expect `status == "ok"` in mock mode and two answers in `env["answers"]`.
- Real API: enable `POLLUX_USE_REAL_API=1` and set `GEMINI_API_KEY`; see How‑to → [Verify Real API](verify-real-api.md).

## 3) Per‑source analysis (fan‑out)

Ask the same question across many sources and aggregate answers with bounded client‑side fan‑out using `run_parallel`:

```python
import asyncio
from pollux import types
from pollux.frontdoor import run_parallel

async def main() -> None:
    srcs = types.sources_from_directory("research_papers/")
    env = await run_parallel("Summarize each file", sources=srcs, concurrency=4)
    print(env["status"], len(env["answers"]))

asyncio.run(main())
```

Verification

- Expect `status` to be `ok` or `partial` depending on per‑file errors.
- `env["metrics"]["per_prompt"]` includes per‑source metadata.

## Troubleshooting

- File not found: ensure relative paths are correct and readable.
- Unsupported URL: use `from_youtube`/`from_arxiv` or `from_uri(uri, mime_type)` if you know the MIME type.
- Large PDFs or remote files: consider enabling Remote File Materialization (How‑to → [Remote File Materialization](remote-file-materialization.md)).
