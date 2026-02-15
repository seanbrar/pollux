#!/usr/bin/env python3
"""Prepare local demo data packs for cookbook recipes.

Usage:
  python scripts/demo_data.py --text medium              # default
  python scripts/demo_data.py --text full
  python scripts/demo_data.py --text medium --media basic

Writes under `cookbook/data/demo/` by default:
  - text-medium/input.txt  (≈240k chars slice ~50-60k tokens)
  - text-full/input.txt    (full tinyshakespeare)

With `--media basic`, also prepares `multimodal-basic/` containing:
  - sample.pdf, sample_image.jpg, sample_video.mp4, sample_audio.mp3

Idempotent: caches the source file at `cookbook/data/demo/.cache/`.

Design goals for scripts:
  - Data-centric pack specifications (clear extension points)
  - Pluggable fetch layer (testable and robust)
  - Strict/CI mode (non-zero exit on failures)
  - Lightweight logging (standardized, quiet/verbose toggles)
"""

from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import logging
from pathlib import Path
import sys
import time
from typing import IO, TYPE_CHECKING, Protocol, cast
import urllib.error
import urllib.request

if TYPE_CHECKING:  # pragma: no cover - typing-only import at runtime
    from collections.abc import Sequence

TINY_SHAKESPEARE_URL = "https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt"


@dataclass(frozen=True, slots=True)
class MediaResource:
    """A small, public media file to fetch for demos."""

    name: str
    urls: tuple[str, ...]


MEDIA_BASIC: tuple[MediaResource, ...] = (
    # Minimal, public, small files for multimodal demos.
    MediaResource(
        name="sample.pdf",
        urls=(
            "https://www.rfc-editor.org/rfc/pdfrfc/rfc1149.txt.pdf",
            # Fallback small PDF (stable public test file)
            "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        ),
    ),
    MediaResource(
        name="sample_image.jpg",
        urls=(
            "https://upload.wikimedia.org/wikipedia/commons/thumb/9/97/The_Earth_seen_from_Apollo_17.jpg/500px-The_Earth_seen_from_Apollo_17.jpg",
            "https://picsum.photos/seed/pollux/320/240.jpg",
        ),
    ),
    MediaResource(
        name="sample_video.mp4",
        urls=(
            "https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4",
            "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/240/Big_Buck_Bunny_240_1mb.mp4",
        ),
    ),
    MediaResource(
        name="sample_audio.mp3",
        urls=(
            "https://samplelib.com/lib/preview/mp3/sample-3s.mp3",
            "https://sample-videos.com/audio/mp3/crowd-cheering.mp3",
        ),
    ),
)


class OpenUrl(Protocol):
    """Protocol for an opener returning a binary file-like HTTP response."""

    def __call__(self, url: str, timeout: float, user_agent: str) -> IO[bytes]:
        """Open the URL and return a binary file-like HTTP response."""


def _default_open_url(url: str, timeout: float, user_agent: str) -> IO[bytes]:
    """Default HTTP opener used by downloads (urllib under the hood).

    Args:
        url: Source URL to request.
        timeout: Timeout in seconds.
        user_agent: User-Agent header value.

    Returns:
        A binary file-like HTTP response object.
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    return cast("IO[bytes]", urllib.request.urlopen(req, timeout=timeout))


def download_with_retries(
    sources: Sequence[str],
    dest: Path,
    *,
    max_retries: int = 2,
    base_backoff: float = 1.5,
    timeout: float = 20.0,
    open_url: OpenUrl | None = None,
) -> bool:
    """Try multiple source URLs with basic retries and backoff.

    Args:
        sources: Candidate URLs to try in order.
        dest: Destination path to write the content to.
        max_retries: Attempts per source before trying the next one.
        base_backoff: Exponential base for sleep between retries.
        timeout: HTTP request timeout in seconds.
        open_url: Optional opener function for dependency injection/testing.

    Returns:
        True on success; False if all sources fail.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest.with_suffix(dest.suffix + ".part")

    ua = (
        "pollux-cookbook/1.0 (+https://github.com/) "
        f"python-urllib/{sys.version_info.major}.{sys.version_info.minor}"
    )
    opener = open_url or _default_open_url

    def try_one(url: str) -> bool:
        for attempt in range(1, max_retries + 1):
            try:
                with (
                    opener(url, timeout, ua) as resp,
                    temp_path.open("wb") as f,
                ):
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                temp_path.replace(dest)
                return True
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                OSError,
            ) as e:
                wait = base_backoff**attempt
                logging.warning(
                    "attempt %s/%s failed for %s: %s. retrying in %.1fs...",
                    attempt,
                    max_retries,
                    url,
                    e,
                    wait,
                )
                with contextlib.suppress(Exception):
                    time.sleep(min(wait, 10.0))
                with contextlib.suppress(OSError):
                    if temp_path.exists():
                        temp_path.unlink()
        return False

    return any(try_one(u) for u in sources)


def ensure_cached(cache_dir: Path) -> Path:
    """Ensure the tinyshakespeare source is present in ``cache_dir``.

    Returns:
        Path to the cached file. If the network is unavailable, a small
        placeholder sample is written to keep workflows unblocked.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / "tinyshakespeare_input.txt"
    if cached.exists() and cached.stat().st_size > 0:
        return cached
    logging.info("downloading tinyshakespeare to cache ...")
    ok = download_with_retries([TINY_SHAKESPEARE_URL], cached)
    if not ok:
        # Graceful offline fallback: seed with a tiny built-in sample.
        logging.warning(
            "failed to download tinyshakespeare; writing a small placeholder sample instead",
        )
        placeholder = (
            b"From fairest creatures we desire increase,\n"
            b"That thereby beauty's rose might never die,\n"
            b"But as the riper should by time decease,\n"
            b"His tender heir might bear his memory.\n"
        )
        cached.write_bytes(placeholder)
    return cached


def write_full(cache_file: Path, out_dir: Path) -> None:
    """Write the full cached text into ``out_dir/input.txt``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "input.txt").write_bytes(cache_file.read_bytes())


def write_medium(cache_file: Path, out_dir: Path, *, chars: int = 240_000) -> None:
    """Write a medium text pack with two comparable files into ``out_dir``.

    - ``input.txt``: first ``chars`` bytes of tinyshakespeare
    - ``compare.txt``: a later slice of half-length to support comparisons

    The second file is intentionally similar in domain/voice to make
    comparative-analysis recipes work out-of-the-box.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    data = cache_file.read_bytes()
    n = len(data)
    # Primary slice from the start; simple and stable.
    primary = data[: min(chars, n)]
    (out_dir / "input.txt").write_bytes(primary)

    # Secondary slice from mid-file to provide a different but similar sample.
    if n > 2_000:
        half_len = max(1, min(max(1, n // 3), max(1, len(primary) // 2)))
        start = max(0, min(n - half_len, n // 2))
        secondary = data[start : start + half_len]
    else:
        secondary = primary
    (out_dir / "compare.txt").write_bytes(secondary)


def write_media_basic(base: Path) -> list[tuple[str, str]]:
    """Write a small multimodal set into ``base / 'multimodal-basic'``.

    Files: sample.pdf, sample_image.jpg, sample_video.mp4, sample_audio.mp3

    Returns:
        A list of ``(name, first_url)`` pairs for downloads that failed.
    """
    out_dir = base / "multimodal-basic"
    out_dir.mkdir(parents=True, exist_ok=True)
    failures: list[tuple[str, str]] = []
    for res in MEDIA_BASIC:
        dest = out_dir / res.name
        if dest.exists() and dest.stat().st_size > 0:
            continue
        logging.info("downloading %s ...", res.name)
        ok = download_with_retries(res.urls, dest)
        if not ok:
            failures.append((res.name, res.urls[0]))
    return failures


def main() -> int:
    """CLI entry: prepare the requested demo data pack."""
    parser = argparse.ArgumentParser(description="Prepare demo data packs")
    parser.add_argument(
        "--text",
        choices=["medium", "full"],
        default="medium",
        help="Which text demo pack to prepare",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path("cookbook/data/demo"),
        help="Destination base directory",
    )
    parser.add_argument(
        "--media",
        choices=["none", "basic"],
        default="basic",
        help="Optionally prepare a minimal multimodal pack",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any download fails (for CI)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity",
    )
    parser.add_argument(
        "--no-pretty",
        action="store_false",
        dest="pretty",
        default=True,
        help="Disable pretty output symbols",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s: %(message)s",
    )

    base = args.dest
    cache = ensure_cached(base / ".cache")

    if args.text == "full":
        write_full(cache, base / "text-full")
        logging.info(
            "%s text-full ready at %s", "✅" if args.pretty else "", base / "text-full"
        )
    else:
        write_medium(cache, base / "text-medium")
        logging.info(
            "%s text-medium ready at %s",
            "✅" if args.pretty else "",
            base / "text-medium",
        )

    if args.media == "basic":
        failures = write_media_basic(base)
        if failures:
            logging.error("completed with media download failures:")
            for n, u in failures:
                logging.error("  - %s: %s", n, u)
            if args.strict:
                return 2
        logging.info(
            "%s multimodal-basic ready at %s",
            "✅" if args.pretty else "",
            base / "multimodal-basic",
        )

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
