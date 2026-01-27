"""Shared helpers for deterministic cache identity.

These helpers centralize how we compute the registry key for shared-context
caches so both CacheStage and APIHandler can operate consistently without
duplicated logic or cross-imports.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pollux.core.types import PlannedCommand


def history_to_text(turns: tuple[Any, ...]) -> str:
    """Convert turns to text format for cache identity.

    Args:
        turns: Tuple of turns with question/answer attributes.

    Returns:
        Formatted conversation history as newline-separated text.
    """
    if not turns:
        return ""
    lines: list[str] = []
    for t in turns:
        lines.append(f"User: {t.question}")
        lines.append(f"Assistant: {t.answer}")
    return "\n".join(lines)


def det_shared_key(
    model_name: str, system_instruction: str | None, command: PlannedCommand
) -> str:
    """Deterministic key for shared-context cache identity.

    Uses model, system instruction, conversation history and resolved sources.
    """
    history_text = history_to_text(command.resolved.initial.history)
    sources = [
        {
            "id": str(s.identifier),
            "mt": s.mime_type,
            "sz": s.size_bytes,
        }
        for s in command.resolved.resolved_sources
    ]
    payload = {
        "model": model_name,
        "system": system_instruction,
        "history": history_text,
        "sources": sources,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
