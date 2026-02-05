"""Shared output helpers for cookbook recipe terminal presentation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cookbook.utils.runtime import print_run_mode, usage_tokens

if TYPE_CHECKING:
    from pollux import Config
    from pollux.result import ResultEnvelope


def print_header(title: str, *, config: Config) -> None:
    """Print recipe title with a consistent runtime mode line."""
    print(title)
    print_run_mode(config)


def print_section(title: str) -> None:
    """Print a named section heading."""
    print(f"\n{title}")


def print_kv_rows(rows: list[tuple[str, object]]) -> None:
    """Print compact key/value rows using a uniform bullet style."""
    for key, value in rows:
        print(f"- {key}: {value}")


def print_excerpt(title: str, text: str, *, limit: int = 400) -> None:
    """Print a clipped text block when non-empty."""
    if not text:
        return
    clipped = text[:limit] + ("..." if len(text) > limit else "")
    print_section(title)
    print(clipped)


def print_usage(envelope: ResultEnvelope) -> None:
    """Print token usage when available."""
    tokens = usage_tokens(envelope)
    if tokens is None:
        return
    print_section("Usage")
    print_kv_rows([("Total tokens", tokens)])


def print_learning_hints(hints: list[str], *, title: str = "Coach notes") -> None:
    """Print short coaching bullets that explain what to do next."""
    if not hints:
        return
    print_section(title)
    for hint in hints:
        print(f"- {hint}")
