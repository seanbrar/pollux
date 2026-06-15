"""Source-to-parts compilation shared by the execution and caching paths.

``build_shared_parts`` turns an environment's stable sources into the neutral
"parts" shape adapters consume: inline text for text/JSON sources, a file
placeholder (``{"file_path", "mime_type"}``) for local files awaiting upload,
and a URI part (``{"uri", "mime_type"}``) for remote sources. Provider hints
ride along when the active provider declares them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pollux.source import Source


def build_shared_parts(
    sources: tuple[Source, ...],
    *,
    provider: str | None = None,
) -> list[Any]:
    """Convert sources to API parts."""
    parts: list[Any] = []

    for source in sources:
        provider_hints = source.provider_hints_for(provider)

        if source.source_type in {"text", "json"}:
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
            # File placeholder - resolved to a provider asset during execution.
            part: dict[str, Any] = {
                "file_path": source.identifier,
                "mime_type": source.mime_type,
            }
            if provider_hints is not None:
                part["provider_hints"] = provider_hints
            parts.append(part)
        else:
            part = {"uri": source.identifier, "mime_type": source.mime_type}
            if provider_hints is not None:
                part["provider_hints"] = provider_hints
            parts.append(part)

    return parts
