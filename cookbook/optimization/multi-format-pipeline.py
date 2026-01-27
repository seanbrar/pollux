#!/usr/bin/env python3
"""🎯 Recipe: Multi-Format Pipeline (PDF + Image + Video)

When you need to: Extract holistic insights from mixed media sources together
in one analysis pass.

Ingredients:
- A mix of PDF/TXT/PNG/MP4 files
- `GEMINI_API_KEY` set in the environment

What you'll learn:
- Build a mixed list of `Source` objects
- Ask layered prompts to combine insights
- Inspect results and usage

Note:
- Videos may require processing time by the provider before they become usable.
  This recipe uses an extension helper (`pollux.extensions.provider_uploads`)
  to pre-upload the video and wait until it reaches the ACTIVE state. If the
  video is not ready within the timeout, the recipe proceeds with the other
  sources and prints a friendly note.

Difficulty: ⭐⭐⭐
Time: ~10-12 minutes
"""

from __future__ import annotations

import argparse
import asyncio
import mimetypes
from pathlib import Path

from cookbook.utils.demo_inputs import DEFAULT_MEDIA_DEMO_DIR, pick_file_by_ext
from cookbook.utils.retry import retry_async
from pollux import types
from pollux.extensions.provider_uploads import (
    UploadInactiveError,
    preupload_and_wait_active,
)
from pollux.frontdoor import run_batch


def _pick_file_by_ext(root: Path, exts: list[str]) -> Path | None:
    return pick_file_by_ext(root, exts)


async def main_async(
    pdf: Path | None, image: Path | None, video: Path | None, base_dir: Path | None
) -> None:
    if pdf is None or image is None or video is None:
        base = base_dir or DEFAULT_MEDIA_DEMO_DIR
        if not base.exists():
            raise SystemExit(
                "Missing inputs. Run `make demo-data` or pass --pdf/--image/--video/--input."
            )
        pdf = pdf or _pick_file_by_ext(base, [".pdf", ".txt"]) or None
        image = image or _pick_file_by_ext(base, [".png", ".jpg", ".jpeg"]) or None
        video = video or _pick_file_by_ext(base, [".mp4", ".mov"]) or None
    # Guard against None before checking .exists()
    sources: list[types.Source] = []
    for p in (pdf, image):
        if p and p.exists():
            sources.append(types.Source.from_file(p))
    # Handle video: best-effort pre-upload and wait for ACTIVE
    if video and video.exists():
        try:
            print("Pre-uploading video and waiting for ACTIVE state...")
            uri = preupload_and_wait_active(video)
            mime, _ = mimetypes.guess_type(str(video))
            sources.append(types.Source.from_uri(uri, mime_type=mime or "video/mp4"))
        except (ImportError, UploadInactiveError, RuntimeError) as e:
            print(f"Note: video not ready ({e}). Proceeding without video for now.")
        except Exception as e:
            print(f"Note: pre-upload unavailable ({e}); using direct upload.")
            sources.append(types.Source.from_file(video))
    if not sources:
        raise SystemExit("Provide at least one existing file among pdf/image/video")

    prompts = [
        "Summarize each source in 1-2 sentences.",
        "Synthesize: what common themes emerge across the media?",
        "List 3 actionable recommendations grounded in the content.",
    ]
    env = await retry_async(
        lambda: run_batch(prompts, sources, prefer_json=False),
        retries=4,
        initial_delay=1.5,
        backoff=1.8,
    )
    print(f"Status: {env.get('status', 'ok')}")
    ans = env.get("answers", [])
    if ans:
        print("\n📋 Synthesis (first 500 chars):\n")
        print(str(ans[-1])[:500])


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-format analysis pipeline")
    parser.add_argument("--input", type=Path, default=None, help="Directory to search")
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="PDF or text file",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="Image file",
    )
    parser.add_argument(
        "--video",
        type=Path,
        default=None,
        help="Video file",
    )
    parser.add_argument("--data-dir", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    print("Note: File size/count affect runtime and tokens.")
    base = args.input or args.data_dir
    asyncio.run(main_async(args.pdf, args.image, args.video, base))


if __name__ == "__main__":
    main()
