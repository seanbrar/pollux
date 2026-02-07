"""Helpers for resolving cookbook demo inputs and user-provided paths."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

_COOKBOOK_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEXT_DEMO_DIR = _COOKBOOK_ROOT / "data" / "demo" / "text-medium"
DEFAULT_MEDIA_DEMO_DIR = _COOKBOOK_ROOT / "data" / "demo" / "multimodal-basic"


def resolve_dir_or_exit(user_path: Path | None, fallback: Path, *, hint: str) -> Path:
    """Return a usable directory or exit with a friendly hint.

    - If ``user_path`` is provided, require it to exist.
    - Otherwise prefer ``fallback`` if it exists.
    - If neither exists, exit with a one-line actionable message (``hint``).
    """
    if user_path is not None:
        if user_path.exists():
            return user_path
        raise SystemExit(f"Directory not found: {user_path}")
    if fallback.exists():
        return fallback
    print(hint, file=sys.stderr)
    raise SystemExit(2)


def resolve_file_or_exit(
    user_path: Path | None,
    *,
    search_dir: Path,
    exts: Iterable[str],
    hint: str,
) -> Path:
    """Return a file path by preferring ``user_path`` or picking from ``search_dir``.

    - If ``user_path`` is provided, require it to exist.
    - Otherwise pick first matching extension from ``search_dir``.
    - On failure, print ``hint`` and exit.
    """
    if user_path is not None:
        if user_path.exists():
            return user_path
        raise SystemExit(f"File not found: {user_path}")
    if not search_dir.exists():
        print(hint, file=sys.stderr)
        raise SystemExit(2)
    pick = pick_file_by_ext(search_dir, exts)
    if pick is not None:
        return pick
    print(hint, file=sys.stderr)
    raise SystemExit(2)


def pick_file_by_ext(root: Path, exts: Iterable[str]) -> Path | None:
    """Return the first file under ``root`` with an allowed extension.

    Extensions are case-insensitive and may include the dot (e.g., ".mp4").
    """
    allowed = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in allowed:
            return p
    return None


def pick_files_by_ext(root: Path, exts: Iterable[str], limit: int) -> list[Path]:
    """Return up to ``limit`` files under ``root`` matching ``exts``.

    Files are returned in stable sorted order by path.
    """
    allowed = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts}
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in allowed:
            out.append(p)
            if len(out) >= max(1, int(limit)):
                break
    return out


__all__ = [
    "DEFAULT_MEDIA_DEMO_DIR",
    "DEFAULT_TEXT_DEMO_DIR",
    "pick_file_by_ext",
    "pick_files_by_ext",
    "resolve_dir_or_exit",
    "resolve_file_or_exit",
]
