#!/usr/bin/env python3
"""🎯 Recipe: Extract Video Insights.

When you need to: Pull highlights, scenes, or key entities from a video file.

Ingredients:
- A small video file (MP4/MOV)
- `GEMINI_API_KEY` set in the environment

What you'll learn:
- Pass videos as `Source` objects
- Ask targeted questions to extract structure
- Print concise results with usage

Note:
- Videos may require processing time by the provider before they become usable.
  This recipe uses an extension helper (`pollux.extensions.provider_uploads`)
  to pre-upload the video and wait until it reaches the ACTIVE state. If the
  video is not ready in time, it suggests re-running after ~1–2 minutes.

Difficulty: ⭐⭐
Time: ~8 minutes
"""

from __future__ import annotations

import argparse
import asyncio
import mimetypes
from pathlib import Path
from typing import TYPE_CHECKING

from cookbook.utils.demo_inputs import DEFAULT_MEDIA_DEMO_DIR, pick_file_by_ext
from cookbook.utils.retry import retry_async
from pollux import types
from pollux.extensions.provider_uploads import (
    UploadInactiveError,
    preupload_and_wait_active,
)
from pollux.frontdoor import run_batch

if TYPE_CHECKING:
    from pollux.core.result_envelope import ResultEnvelope


def _first(env: ResultEnvelope) -> str:
    ans = env.get("answers", [])
    return str(ans[0]) if ans else ""


async def main_async(path: Path) -> None:
    # Best-effort: try provider pre-upload and ACTIVE wait, then fall back.
    try:
        print("Attempting pre-upload and ACTIVE wait...")
        uri = preupload_and_wait_active(path)
        # Derive a best-effort MIME type from the path extension
        mime, _ = mimetypes.guess_type(str(path))
        src = types.Source.from_uri(uri, mime_type=mime or "video/mp4")
    except UploadInactiveError as e:
        print(
            "Video upload is still processing (not ACTIVE). Please wait ~1–2 minutes "
            "and re-run this recipe. Details: " + str(e)
        )
        return
    except (ImportError, RuntimeError, Exception) as e:
        # Fall back to direct upload with retries for any pre-upload issues
        print(
            f"Note: pre-upload unavailable ({e}); trying direct upload with retries..."
        )
        src = types.Source.from_file(path)
    prompts = [
        "List 3 key moments with timestamps if visible.",
        "Identify main entities/objects and their roles.",
    ]
    # Video uploads may require brief processing time before ACTIVE state.
    env = await retry_async(
        lambda: run_batch(prompts, [src], prefer_json=False),
        retries=4,
        initial_delay=1.5,
        backoff=1.8,
    )
    print(f"Status: {env.get('status', 'ok')}")
    print("\n🎞️  Highlights (first 400 chars):\n")
    print(_first(env)[:400])


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract insights from a video")
    parser.add_argument("--input", type=Path, default=None, help="Path to a video")
    args = parser.parse_args()
    video_path: Path
    if args.input is not None:
        video_path = args.input
    else:
        demo_dir = DEFAULT_MEDIA_DEMO_DIR
        if not demo_dir.exists():
            raise SystemExit("No input provided. Run `make demo-data` or pass --input.")
        pick = pick_file_by_ext(demo_dir, [".mp4", ".mov"]) or None
        if pick is None:
            raise SystemExit(
                "No video found in demo dir. Run `make demo-data` or pass --input."
            )
        video_path = pick
    if not video_path.exists():
        raise SystemExit(f"File not found: {video_path}")
    asyncio.run(main_async(video_path))


if __name__ == "__main__":
    main()
