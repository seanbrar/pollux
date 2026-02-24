"""Phase 1: Request normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pollux.errors import ConfigurationError, SourceError
from pollux.options import Options
from pollux.source import Source

if TYPE_CHECKING:
    from pollux.config import Config


@dataclass(frozen=True)
class Request:
    """Normalized request ready for planning."""

    sources: tuple[Source, ...]
    prompts: tuple[str, ...]
    config: Config
    options: Options


def normalize_request(
    prompts: tuple[str, ...] | list[str] | str,
    sources: tuple[Source, ...] | list[Source],
    config: Config,
    *,
    options: Options | None = None,
) -> Request:
    """Validate and normalize inputs into a Request.

    Args:
        prompts: One or more prompts.
        sources: Sources for context (can be empty tuple).
        config: Configuration specifying provider and model.
        options: Optional additive execution options.

    Returns:
        Normalized Request ready for planning.

    Raises:
        SourceError: If sources are invalid.
    """
    # Normalize prompts to tuple
    prompts = (prompts,) if isinstance(prompts, str) else tuple(prompts)

    # Validate prompts (empty list is a valid no-op for run_many)
    for i, p in enumerate(prompts):
        if not isinstance(p, str) or not p.strip():
            idx_label = f"prompts[{i}]" if len(prompts) > 1 else "prompt"
            raise ConfigurationError(
                f"{idx_label} is empty or whitespace-only",
                hint="Each prompt must be a non-empty string.",
            )

    # Validate sources
    source_tuple = tuple(sources)
    for s in source_tuple:
        if not isinstance(s, Source):
            raise SourceError(
                f"Expected Source, got {type(s).__name__}",
                hint="Use Source.from_text(), Source.from_file(), etc.",
            )

    return Request(
        sources=source_tuple,
        prompts=prompts,
        config=config,
        options=options or Options(),
    )
