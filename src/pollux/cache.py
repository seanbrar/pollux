"""Cache: Content-hash identity with expires_at tracking."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import time
from typing import TYPE_CHECKING, Any

from pollux._singleflight import singleflight_cached
from pollux.retry import RetryPolicy, retry_async, should_retry_side_effect

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
    retry_policy: RetryPolicy | None = None,
) -> str | None:
    """Get existing cache or create new one with single-flight protection.

    Single-flight: concurrent requests for the same key share one creation call.
    """
    if not provider.supports_caching:
        return None

    async def _work() -> str:
        if retry_policy is None or retry_policy.max_attempts <= 1:
            return await provider.create_cache(
                model=model,
                parts=parts,
                system_instruction=system_instruction,
                ttl_seconds=ttl_seconds,
            )

        return await retry_async(
            lambda: provider.create_cache(
                model=model,
                parts=parts,
                system_instruction=system_instruction,
                ttl_seconds=ttl_seconds,
            ),
            policy=retry_policy,
            should_retry=should_retry_side_effect,
        )

    return await singleflight_cached(
        key,
        lock=registry._lock,
        inflight=registry._inflight,
        cache_get=registry.get,
        cache_set=lambda k, v: registry.set(k, v, ttl_seconds),
        work=_work,
    )
