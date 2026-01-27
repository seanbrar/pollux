#!/usr/bin/env python3
"""🎯 Recipe: YouTube Q&A With Clickable Timestamps

When you need to: Ask a question about a single YouTube video and get answers
annotated with timestamps formatted as clickable links.

Ingredients:
- A YouTube URL (watch or youtu.be forms)
- `GEMINI_API_KEY` set in the environment

What you'll learn:
- Use `Source.from_youtube(url)` to analyze a YouTube video
- Prompt pattern to request timestamps with mm:ss or hh:mm:ss
- Post-process answer to add clickable `&t=SSs` links for each timestamp

Difficulty: ⭐⭐
Time: ~8 minutes
"""

from __future__ import annotations

import argparse
import asyncio
import re

from pollux import types
from pollux.frontdoor import run_batch

TIMESTAMPS_PROMPT = (
    "Answer concisely. Include timestamps like [mm:ss] or [hh:mm:ss] near key points."
)


def _parse_timestamps(answer: str) -> list[tuple[str, int]]:
    """Extract timestamps as (display, seconds) tuples.

    Supports [mm:ss] and [hh:mm:ss] in a single pass.
    """
    out: list[tuple[str, int]] = []
    pattern = re.compile(r"\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\]")
    for m in pattern.finditer(answer):
        h_str, m_str, s_str = m.group(1), m.group(2), m.group(3)
        hours = int(h_str) if h_str is not None else 0
        minutes = int(m_str)
        seconds = int(s_str)
        total = hours * 3600 + minutes * 60 + seconds
        out.append((m.group(0), total))
    # Deduplicate
    seen: set[tuple[str, int]] = set()
    uniq: list[tuple[str, int]] = []
    for disp, secs in out:
        key = (disp, secs)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((disp, secs))
    return uniq


def _attach_links(answer: str, base_url: str) -> str:
    pairs = _parse_timestamps(answer)
    out = answer
    for disp, secs in pairs:
        url = f"{base_url}&t={secs}s" if "?" in base_url else f"{base_url}?t={secs}s"
        out = out.replace(disp, f"{disp} ({url})")
    return out


async def main_async(url: str, question: str) -> None:
    src = types.Source.from_youtube(url)
    env = await run_batch([question, TIMESTAMPS_PROMPT], [src], prefer_json=False)
    answers = env.get("answers", [])
    combined = "\n\n".join(str(a) for a in answers)
    with_links = _attach_links(combined, url)
    print(with_links[:1200] + ("..." if len(with_links) > 1200 else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube Q&A with timestamps")
    parser.add_argument("url", help="YouTube video URL (watch or youtu.be)")
    parser.add_argument(
        "--question",
        default="What are the 3 key takeaways? Include [mm:ss] timestamps.",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args.url, args.question))


if __name__ == "__main__":
    main()
