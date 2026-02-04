"""Phase 2: Execution planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pollux.request import Request
    from pollux.source import Source


@dataclass(frozen=True)
class Call:
    """A single API call to execute."""

    model: str
    prompt: str
    parts: tuple[Any, ...] = ()
    system_instruction: str | None = None


@dataclass(frozen=True)
class Plan:
    """Execution plan with calls and shared context."""

    request: Request
    calls: tuple[Call, ...]
    shared_parts: tuple[Any, ...] = ()
    use_cache: bool = False
    cache_key: str | None = None


def build_plan(request: Request) -> Plan:
    """Build execution plan from normalized request.

    Handles both single-prompt and vectorized (multi-prompt) scenarios.
    """
    config = request.config
    sources = request.sources
    prompts = request.prompts

    # Build shared parts from sources
    shared_parts = _build_shared_parts(sources)

    # Determine if caching should be used
    use_cache = config.enable_caching and len(shared_parts) > 0
    cache_key = None

    if use_cache:
        from pollux.cache import compute_cache_key

        cache_key = compute_cache_key(config.model, sources)

    # Build calls - one per prompt for vectorized execution
    calls = tuple(
        Call(
            model=config.model,
            prompt=prompt,
            parts=tuple(shared_parts),
        )
        for prompt in prompts
    )

    return Plan(
        request=request,
        calls=calls,
        shared_parts=tuple(shared_parts),
        use_cache=use_cache,
        cache_key=cache_key,
    )


def _build_shared_parts(sources: tuple[Source, ...]) -> list[Any]:
    """Convert sources to API parts."""
    parts: list[Any] = []

    for source in sources:
        if source.source_type == "text":
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
