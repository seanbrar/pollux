"""Timestamp linker utility.

Parses timestamps (hh:mm or hh:mm:ss) found in answers and enriches a
`ResultEnvelope` with structured timestamp data. When a YouTube URL is among
the sources, it also attaches a URL with a `?t=<seconds>` query parameter.

Design:
- Pure, idempotent, and side-effect free. Returns a new envelope dict.
- Does not depend on provider SDKs; callers pass a minimal list of source
  identifiers (e.g., strings or objects with ``identifier`` attribute).

Typical usage (cookbook step):
    enriched = link_timestamps(envelope, sources)

Enhancements:
- Newly extracted timestamps are normalized as ``HH:MM:SS`` and a
  human-friendly ``display`` field provides compact formatting
  (``M:SS`` or ``H:MM:SS``). Existing entries in the envelope are
  preserved as-is for backward compatibility, but are enriched with
  missing fields (e.g., ``url``, ``display``) when possible.
- Alternate time syntaxes are supported: ``1m02s``, ``1h2m3s``, ``90s``.
- When multiple YouTube URLs are present, set ``multi_url=True`` to include
  a per-timestamp ``urls`` list (in addition to the single ``url`` for
  backward compatibility).
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, runtime_checkable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

if TYPE_CHECKING:  # typing-only import to satisfy TC003 rule
    from collections.abc import Iterable


class TimestampEntry(TypedDict, total=False):
    """Structured timestamp entry.

    Fields:
    - timestamp: Normalized time in HH:MM:SS format.
    - seconds: Integer seconds from start.
    - url: Optional URL pointing to the timestamp (e.g., YouTube with `t=`).
    - display: Minimal, human-friendly format (e.g., M:SS or H:MM:SS).
    - urls: Optional list of URLs when multiple sources exist.
    """

    timestamp: str
    seconds: int
    url: str
    display: str
    urls: list[str]


@runtime_checkable
class HasIdentifier(Protocol):  # pragma: no cover - typing interface only
    """Typing protocol for objects that expose an `identifier` attribute."""

    identifier: Any


TimestampDict = dict[str, Any]


_TS_RE = re.compile(r"\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\b")
# Matches component style: 1h2m3s, 1m02s, 90s (seconds required)
_COMPONENT_RE = re.compile(
    r"\b(?:(\d{1,3})\s*[hH]\s*)?(?:(\d{1,2})\s*[mM]\s*)?(?:(\d{1,2})\s*[sS])\b"
)


def _to_seconds(m: re.Match[str]) -> tuple[str, int] | None:
    """Convert regex match to (HH:MM:SS, seconds).

    Returns None for invalid minute/second ranges.
    """
    h_raw = m.group(1)
    mnt = int(m.group(2))
    sec = int(m.group(3))
    if not (0 <= mnt < 60 and 0 <= sec < 60):
        return None
    hours = int(h_raw) if h_raw else 0
    total = hours * 3600 + mnt * 60 + sec
    ts = f"{hours:02d}:{mnt:02d}:{sec:02d}"
    return ts, total


def _fmt_seconds(total: int) -> str:
    """Format seconds as HH:MM:SS."""
    if total < 0:
        total = 0
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_display(total: int) -> str:
    """Format seconds as human-friendly display.

    - >= 1 hour: H:MM:SS (no leading zero hours)
    - < 1 hour: M:SS (no leading zero minutes)
    """
    if total < 0:
        total = 0
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _component_to_seconds(m: re.Match[str]) -> tuple[str, int] | None:
    """Convert component style (Hh Mm Ss) to (HH:MM:SS, seconds)."""
    hours = int(m.group(1)) if m.group(1) else 0
    minutes = int(m.group(2)) if m.group(2) else 0
    seconds = int(m.group(3)) if m.group(3) else 0
    if hours < 0 or minutes < 0 or seconds < 0:
        return None
    total = hours * 3600 + minutes * 60 + seconds
    ts = _fmt_seconds(total)
    return ts, total


def _iter_youtube_urls(sources: Iterable[Any]) -> Iterable[str]:
    for s in sources:
        try:
            # Best-effort to extract an identifier-like attribute
            ident = getattr(s, "identifier", s)
        except Exception:
            ident = s
        if not isinstance(ident, str):
            continue
        lower = ident.lower()
        if "youtube.com/" in lower or "youtu.be/" in lower:
            yield ident


def _append_time_param(url: str, seconds: int) -> str:
    """Append or replace `t` query param with the provided seconds.

    Uses robust parsing to remove any existing `t` parameters while preserving
    all other query parameters and the URL structure (including fragments).
    The new `t` is appended at the end of the query string to keep the
    original parameter order stable.
    """
    parts = urlsplit(url)
    query_pairs = [
        (k, v) for (k, v) in parse_qsl(parts.query, keep_blank_values=True) if k != "t"
    ]
    query_pairs.append(("t", str(int(seconds))))
    new_query = urlencode(query_pairs, doseq=True)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
    )


def link_timestamps(
    envelope: dict[str, Any],
    sources: Iterable[Any],
    *,
    multi_url: bool = False,
) -> dict[str, Any]:
    """Return a new envelope enriched with structured timestamps.

    Args:
        envelope: ResultEnvelope-like mapping.
        sources: Sequence of source identifiers or `Source` objects.
        multi_url: When True and multiple YouTube sources exist, include a
            sorted list of per-timestamp URLs under the `urls` key while also
            setting the single `url` for backward compatibility.

    Returns:
        New dict with `structured_data.timestamps` appended. Idempotent.
    """
    out = deepcopy(envelope)
    answers = out.get("answers") or []
    if not isinstance(answers, list):
        return out

    # Extract unique timestamps across answers
    seen: set[tuple[str, int]] = set()
    timestamps: list[TimestampEntry] = []
    for ans in answers:
        if not isinstance(ans, str):
            continue
        for m in _TS_RE.finditer(ans):
            converted = _to_seconds(m)
            if not converted:
                continue
            ts, secs = converted
            key = (ts, secs)
            if key in seen:
                continue
            seen.add(key)
            timestamps.append(
                {"timestamp": ts, "seconds": secs, "display": _fmt_display(secs)}
            )
        for m in _COMPONENT_RE.finditer(ans):
            converted2 = _component_to_seconds(m)
            if not converted2:
                continue
            ts2, secs2 = converted2
            key2 = (ts2, secs2)
            if key2 in seen:
                continue
            seen.add(key2)
            timestamps.append(
                {"timestamp": ts2, "seconds": secs2, "display": _fmt_display(secs2)}
            )

    if not timestamps:
        return out

    # If youtube sources exist, add a URL per timestamp picking a deterministic URL
    yt_urls = sorted(_iter_youtube_urls(sources))
    yt_url = yt_urls[0] if yt_urls else None
    if yt_url:
        for t in timestamps:
            primary = _append_time_param(yt_url, int(t["seconds"]))
            t["url"] = primary
            if multi_url and len(yt_urls) > 1:
                t["urls"] = [_append_time_param(u, int(t["seconds"])) for u in yt_urls]

    # Merge into structured_data.timestamps without duplication
    sd = out.setdefault("structured_data", {})
    existing = sd.get("timestamps")
    merged: list[TimestampEntry] = []
    existing_set: set[tuple[str, int]] = set()
    if isinstance(existing, list):
        for e in existing:
            if not isinstance(e, dict):
                continue
            ts = str(e.get("timestamp", ""))
            try:
                secs = int(e.get("seconds", 0))
            except Exception:
                secs = 0
            # Use normalized key to avoid duplicate when existing uses MM:SS
            key_ts = _fmt_seconds(secs)
            existing_set.add((key_ts, secs))
            # Enrich existing entries with URL if available and missing
            enriched: TimestampEntry = dict(e)  # type: ignore[assignment]
            if yt_url and "url" not in enriched and ts and secs:
                enriched["url"] = _append_time_param(yt_url, int(secs))
            if multi_url and yt_urls and "urls" not in enriched and secs:
                enriched["urls"] = [_append_time_param(u, int(secs)) for u in yt_urls]
            if secs and "display" not in enriched:
                enriched["display"] = _fmt_display(int(secs))
            merged.append(enriched)
    for t in timestamps:
        key = (t["timestamp"], int(t["seconds"]))
        if key not in existing_set:
            merged.append(t)
            existing_set.add(key)
    sd["timestamps"] = merged

    return out
