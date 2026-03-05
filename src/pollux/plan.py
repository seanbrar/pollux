"""Phase 2: Execution planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pollux.errors import ConfigurationError

if TYPE_CHECKING:
    from pollux.request import Request
    from pollux.source import Source


@dataclass(frozen=True)
class Plan:
    """Execution plan with shared context and optional cache reference."""

    request: Request
    shared_parts: tuple[Any, ...] = ()
    cache_name: str | None = None

    @property
    def n_calls(self) -> int:
        """Number of provider generate calls this plan will execute."""
        return len(self.request.prompts)


def build_plan(request: Request) -> Plan:
    """Build execution plan from normalized request.

    Handles both single-prompt and vectorized (multi-prompt) scenarios.
    Validates cache handle conflicts eagerly so callers get clear errors
    before any network I/O.
    """
    sources = request.sources
    shared_parts = build_shared_parts(sources)

    cache_name: str | None = None
    if request.options.cache is not None:
        cache = request.options.cache
        if cache.provider != request.config.provider:
            raise ConfigurationError(
                "cache handle provider does not match config provider",
                hint=(
                    f"Create the cache with provider={request.config.provider!r} and "
                    "reuse it with the same provider."
                ),
            )
        if cache.model != request.config.model:
            raise ConfigurationError(
                "cache handle model does not match config model",
                hint=(
                    f"Create the cache with model={request.config.model!r} and reuse it "
                    "with the same model."
                ),
            )
        if request.options.system_instruction is not None:
            raise ConfigurationError(
                "system_instruction cannot be used with a cache handle",
                hint=(
                    "Bake the system instruction into create_cache() instead, "
                    "or remove the cache handle."
                ),
            )
        if request.options.tools is not None:
            raise ConfigurationError(
                "tools cannot be used with a cache handle",
                hint=(
                    "Bake tools into create_cache() instead, "
                    "or remove the cache handle."
                ),
            )
        if request.options.tool_choice is not None:
            raise ConfigurationError(
                "tool_choice cannot be used with a cache handle",
                hint=(
                    "Remove tool_choice when using a cache handle, "
                    "or remove the cache handle."
                ),
            )
        if shared_parts:
            raise ConfigurationError(
                "sources cannot be used with a cache handle",
                hint=(
                    "Bake sources into create_cache() instead, "
                    "or remove the cache handle."
                ),
            )
        cache_name = cache.name

    return Plan(
        request=request,
        shared_parts=tuple(shared_parts),
        cache_name=cache_name,
    )


def build_shared_parts(sources: tuple[Source, ...]) -> list[Any]:
    """Convert sources to API parts."""
    parts: list[Any] = []

    for source in sources:
        if source.source_type in {"text", "json"}:
            # Load text content
            try:
                content = source.content_loader()
                text = content.decode("utf-8", errors="replace")
                parts.append(text)
            except Exception as e:
                from pollux.errors import PlanningError

                raise PlanningError(
                    f"Failed to load content from source: {source.identifier}",
                    hint=str(e),
                ) from e
        elif source.source_type == "file":
            # File placeholder - will be uploaded during execution
            parts.append(
                {"file_path": source.identifier, "mime_type": source.mime_type}
            )
        else:
            # URI-based sources
            parts.append({"uri": source.identifier, "mime_type": source.mime_type})

    return parts
