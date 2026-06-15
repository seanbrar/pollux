"""Shared output helpers for cookbook recipe terminal presentation.

These helpers aim for:
- scan-friendly sectioning
- compact, consistent key/value rows
- readable excerpts (clipped, not spammy)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from cookbook.utils.runtime import print_run_mode

if TYPE_CHECKING:
    from pollux import Config, Output, OutputCollection


def _display_path(path: Path) -> str:
    """Prefer short, cwd-relative paths for terminal output."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except Exception:
        return str(path)


def _display_value(value: object) -> str:
    if isinstance(value, Path):
        return _display_path(value)
    return str(value)


def print_header(title: str, *, config: Config) -> None:
    """Print recipe title with a consistent runtime mode line."""
    print(title)
    print("=" * len(title))
    print_run_mode(config)


def print_section(title: str) -> None:
    """Print a named section heading."""
    print(f"\n{title}")
    print("-" * len(title))


def print_kv_rows(rows: list[tuple[str, object]]) -> None:
    """Print compact key/value rows using a uniform bullet style."""
    for key, value in rows:
        rendered = _display_value(value)
        # Preserve readability for multi-line values (indent continuation lines).
        lines = rendered.splitlines() or [""]
        print(f"- {key}: {lines[0]}")
        for cont in lines[1:]:
            print(f"  {' ' * len(key)}  {cont}")


def print_excerpt(title: str, text: str, *, limit: int = 400) -> None:
    """Print a clipped text block when non-empty."""
    if not text:
        return
    cleaned = text.strip()
    clipped = cleaned[:limit] + ("..." if len(cleaned) > limit else "")
    print_section(title)
    for line in clipped.splitlines() or [""]:
        print(f"  {line}")


def print_usage(result: Output | OutputCollection) -> None:
    """Print token usage when available."""
    usage = result.usage
    rows: list[tuple[str, object]] = []
    if usage.total_tokens:
        rows.append(("Total tokens", usage.total_tokens))
    if usage.input_tokens:
        rows.append(("Prompt tokens", usage.input_tokens))
    if usage.output_tokens:
        rows.append(("Completion tokens", usage.output_tokens))

    if not rows:
        return

    print_section("Usage")
    print_kv_rows(rows)


def print_learning_hints(hints: list[str], *, title: str = "Next steps") -> None:
    """Print short coaching bullets that explain what to do next."""
    if not hints:
        return
    print_section(title)
    for hint in hints:
        print(f"- {hint}")
