"""Cache: Content-hash identity with expires_at tracking."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pollux.providers.base import Provider
    from pollux.source import Source


@dataclass
class CacheRegistry:
    """Registry tracking cache entries with expiration."""

    _entries: dict[str, tuple[str, float]] = field(default_factory=dict)
    _inflight: dict[str, asyncio.Future[str]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def get(self, key: str) -> str | None:
        """Get cache name if exists and not expired."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        name, expires_at = entry
        if time.time() >= expires_at:
            del self._entries[key]
            return None
        return name

    def set(self, key: str, name: str, ttl_seconds: int) -> None:
        """Store cache entry with expiration time."""
        expires_at = time.time() + max(0, ttl_seconds)
        self._entries[key] = (name, expires_at)


def compute_cache_key(
    model: str,
    sources: tuple[Source, ...],
    system_instruction: str | None = None,
) -> str:
    """Compute deterministic cache key using content hashes.

    Key = hash(model + system + content digests of sources)
    This fixes the cache identity collision bug where identifier+size was used.
    """
    parts = [model]
    if system_instruction:
        parts.append(system_instruction)

    for source in sources:
        # Use content hash, not identifier
        parts.append(source.content_hash())

    combined = "|".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


async def get_or_create_cache(
    provider: Provider,
    registry: CacheRegistry,
    *,
    key: str,
    model: str,
    parts: list[Any],
    system_instruction: str | None,
    ttl_seconds: int,
) -> str | None:
    """Get existing cache or create new one with single-flight protection.

    Single-flight: concurrent requests for the same key share one creation call.
    """
    if not provider.supports_caching:
        return None

    # Check registry first
    if cached := registry.get(key):
        return cached

    # Single-flight: share inflight creations
    async with registry._lock:
        # Double-check after acquiring lock
        if cached := registry.get(key):
            return cached

        if key in registry._inflight:
            fut = registry._inflight[key]
            creator = False
        else:
            fut = asyncio.get_running_loop().create_future()
            registry._inflight[key] = fut
            creator = True

    if not creator:
        return await fut

    # We are the creator
    try:
        cache_name = await provider.create_cache(
            model=model,
            parts=parts,
            system_instruction=system_instruction,
            ttl_seconds=ttl_seconds,
        )
        registry.set(key, cache_name, ttl_seconds)
        fut.set_result(cache_name)
        return cache_name
    except Exception as e:
        fut.set_exception(e)
        raise
    finally:
        async with registry._lock:
            registry._inflight.pop(key, None)
