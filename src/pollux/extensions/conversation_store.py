"""Append-only, versioned store interfaces and JSON implementation.

Defines the `ConversationStore` protocol and a simple `JSONStore` that
persists conversation state with optimistic concurrency.
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .conversation_types import ConversationState, Exchange

if TYPE_CHECKING:
    import os


class ConversationStore(Protocol):
    """Protocol for loading and appending conversation state."""

    async def load(self, conversation_id: str) -> ConversationState:
        """Load a conversation state by identifier."""
        ...

    async def append(
        self, conversation_id: str, expected_version: int, ex: Exchange
    ) -> ConversationState:
        """Append an exchange using OCC and return the updated state."""
        ...


class JSONStore:
    """Append-only, versioned JSON store (single file mapping id -> state).

    Uses copy-on-write: write to a temp file and rename for atomicity.
    Shape saved per conversation id:
      {
        "sources": [...],
        "turns": [{"user":..., "assistant":..., "error":..., audit...}, ...],
        "cache": {"key":..., "artifacts": [...], "ttl_seconds": ...} | null,
        "version": int
      }
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        """Initialize the store pointing at a JSON file path."""
        self._path = Path(path)

    async def load(self, conversation_id: str) -> ConversationState:
        """Load conversation state or return an empty default state."""
        data = self._read_all()
        entry = data.get(conversation_id)
        if not isinstance(entry, dict):
            return ConversationState(
                sources=(),
                turns=(),
                cache_key=None,
                cache_artifacts=(),
                cache_ttl_seconds=None,
                policy=None,
                version=0,
            )
        sources_raw = entry.get("sources", ())
        sources: tuple[str, ...] = (
            tuple(sources_raw) if isinstance(sources_raw, list | tuple) else ()
        )
        turns_raw = entry.get("turns", [])
        turns: list[Exchange] = []
        if isinstance(turns_raw, list):
            for t in turns_raw:
                if not isinstance(t, dict):
                    continue
                # Normalize warnings tuple if present
                w = t.get("warnings", ())
                warnings: tuple[str, ...]
                if isinstance(w, str):
                    warnings = (w,)
                elif isinstance(w, list | tuple):
                    warnings = tuple(str(x) for x in w)
                else:
                    warnings = ()

                turns.append(
                    Exchange(
                        user=str(t.get("user", "")),
                        assistant=str(t.get("assistant", "")),
                        error=bool(t.get("error", False)),
                        estimate_min=t.get("estimate_min"),
                        estimate_max=t.get("estimate_max"),
                        actual_tokens=t.get("actual_tokens"),
                        in_range=t.get("in_range"),
                        warnings=warnings,
                    )
                )
        cache_raw = entry.get("cache")
        cache_key = None
        cache_artifacts: tuple[str, ...] = ()
        cache_ttl = None
        if isinstance(cache_raw, dict) and cache_raw:
            cache_key = (
                str(cache_raw.get("key")) if cache_raw.get("key") is not None else None
            )
            cache_artifacts = tuple(cache_raw.get("artifacts", ()) or ())
            cache_ttl = cache_raw.get("ttl_seconds")
        version_raw = entry.get("version", 0)
        version = int(version_raw) if isinstance(version_raw, int | float | str) else 0
        return ConversationState(
            sources=sources,
            turns=tuple(turns),
            cache_key=cache_key,
            cache_artifacts=cache_artifacts,
            cache_ttl_seconds=cache_ttl,
            policy=None,
            version=version,
        )

    async def append(
        self, conversation_id: str, expected_version: int, ex: Exchange
    ) -> ConversationState:
        """Append an exchange with optimistic concurrency enforcement."""
        data = self._read_all()
        entry = data.get(conversation_id)
        if not isinstance(entry, dict):
            entry = {
                "sources": [],
                "turns": [],
                "cache": None,
                "version": 0,
            }
        current_version = entry.get("version", 0)
        if not isinstance(current_version, int):
            current_version = 0
        if current_version != expected_version:
            raise RuntimeError(
                f"OCC conflict: expected {expected_version}, got {current_version}"
            )
        # Append new exchange and bump version
        turns_raw = entry.get("turns", [])
        turns = list(turns_raw) if isinstance(turns_raw, list) else []
        turns.append(_exchange_to_dict(ex))
        entry["turns"] = turns
        entry["version"] = current_version + 1
        data[conversation_id] = entry
        self._write_all(data)
        # Return reconstructed state
        return await self.load(conversation_id)

    def _read_all(self) -> dict[str, dict[str, object]]:
        """Read and deserialize the entire JSON file into a mapping."""
        if not self._path.exists():
            return {}
        try:
            result = json.loads(self._path.read_text(encoding="utf-8"))
            return result if isinstance(result, dict) else {}
        except Exception:
            return {}

    def _write_all(self, data: dict[str, dict[str, object]]) -> None:
        """Persist data atomically via temp file rename."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        # Use Path.replace on the temporary file to atomically move into place
        tmp.replace(self._path)


def _exchange_to_dict(ex: Exchange) -> dict[str, object]:
    return asdict(ex)
    # asdict includes our fields already; ensure tuple types serialized
