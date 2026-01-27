"""Lightweight in-memory registries for uploads and caches.

These registries are owned by the executor/runtime and are deliberately simple.
They avoid provider SDK calls; they only store/retrieve previously discovered
identifiers so handlers can reuse them. They are intentionally ephemeral and
process-local; persistence across processes is out of scope here.
"""

from __future__ import annotations

from typing import Any, Protocol


class CacheRegistry:
    """Maps deterministic cache keys to provider cache names, plus metadata.

    Minimal API by design; single-process memory only. Concurrency protection
    is expected to be handled by higher layers via single-flight if needed.

    Primary mapping `get/set` stores provider cache names as strings.
    A separate metadata channel `get_meta/set_meta` stores structured
    information (e.g., cache_name, artifacts from CacheOptions) keyed by the
    same deterministic key. This separation maintains homogeneous value
    types in the primary map and improves robustness and testability.

    Metadata contains execution-relevant information actively maintained
    during cache operations. The API handler writes cache names and
    artifacts from CacheOptions instances to support the hint capsule system.
    While best-effort (failures are logged but don't break execution),
    the metadata provides structured, authoritative information about
    cache usage for audit, debugging, and potential future retrieval.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory mapping for cache keys.

        Creates a process-local store that maps deterministic cache keys to
        provider cache names. No I/O or network calls occur here.
        """
        self._key_to_name: dict[str, str] = {}
        self._meta: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> str | None:
        """Return the provider cache name for `key`, if present.

        Args:
            key: Deterministic key produced by the planner.

        Returns:
            The provider cache name or None.
        """
        return self._key_to_name.get(key)

    def set(self, key: str, name: str) -> None:
        """Associate a deterministic key with a provider cache name."""
        self._key_to_name[key] = name

    # --- Metadata channel ---
    def get_meta(self, key: str) -> dict[str, Any] | None:
        """Return metadata for `key`, if present.

        Stored separately from the primary name mapping to keep value types
        uniform in `get/set` while enabling richer audit/debug information.
        """
        return self._meta.get(key)

    def set_meta(self, key: str, meta: dict[str, Any]) -> None:
        """Associate a metadata mapping with `key`.

        The mapping is stored as-is. Callers should ensure values are
        JSON-serializable if they intend to persist or export them later.
        """
        self._meta[key] = dict(meta)


class FileRegistry:
    """Maps local file identifiers (paths or hashes) to uploaded provider refs.

    Values are provider-shaped objects or neutral `FileRefPart` that the
    handler will coerce to a `FileRefPart` if needed.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory mapping for file uploads.

        Maintains a process-local map from local file identifiers (e.g., paths
        or hashes) to provider-uploaded references for reuse within a run.
        """
        self._id_to_uploaded: dict[str, Any] = {}

    def get(self, local_id: str) -> Any | None:
        """Return the uploaded reference for a local file id, if present."""
        return self._id_to_uploaded.get(local_id)

    def set(self, local_id: str, uploaded: Any) -> None:
        """Associate a local file id with a provider-uploaded reference."""
        self._id_to_uploaded[local_id] = uploaded


class SimpleRegistry(Protocol):
    """Minimal get/set registry protocol used by pipeline handlers.

    This protocol exists to clarify the expected surface used by the handlers
    and to remove incidental ``hasattr`` checks. Implementations are simple,
    in-memory registries with no I/O.
    """

    def get(self, key: str) -> Any | None:
        """Return the value for `key`, if present."""
        ...

    def set(self, key: str, value: Any) -> None:
        """Associate a key with a value."""
        ...
