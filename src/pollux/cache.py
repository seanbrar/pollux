"""Cache: Content-hash identity with expires_at tracking."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import logging
import time
from typing import TYPE_CHECKING, Any

from pollux._singleflight import singleflight_cached
from pollux.errors import ConfigurationError
from pollux.retry import RetryPolicy, retry_async, should_retry_side_effect

if TYPE_CHECKING:
    from pollux.providers.base import Provider
    from pollux.source import Source

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheHandle:
    """Opaque handle returned by ``create_cache()``.

    Pass instances via ``Options(cache=handle)`` to reuse a persistent
    context cache across ``run()`` / ``run_many()`` calls.
    """

    name: str
    model: str
    provider: str
    expires_at: float


@dataclass
class CacheRegistry:
    """Registry tracking cache entries with expiration."""

    _entries: dict[str, tuple[str, float]] = field(default_factory=dict)
    _inflight: dict[str, asyncio.Future[tuple[str, float]]] = field(
        default_factory=dict
    )
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def get(self, key: str) -> tuple[str, float] | None:
        """Get cache entry if exists and not expired."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        _, expires_at = entry
        if time.time() >= expires_at:
            del self._entries[key]
            logger.debug("Cache expired key=%s…", key[:8])
            return None
        return entry

    def set(self, key: str, value: tuple[str, float]) -> None:
        """Store cache entry with expiration time."""
        self._entries[key] = value


def compute_cache_key(
    model: str,
    sources: tuple[Source, ...],
    provider: str | None = None,
    system_instruction: str | None = None,
    tools: list[dict[str, Any]] | list[Any] | None = None,
) -> str:
    """Compute deterministic cache key using content hashes.

    Key = hash(model + provider + system + content digests of sources)
    This fixes the cache identity collision bug where identifier+size was used.
    """
    parts = [model]
    if provider:
        parts.append(provider)
    if system_instruction:
        parts.append(system_instruction)
    if tools:
        import json

        try:
            # sort_keys to ensure deterministic JSON representation
            parts.append(json.dumps(tools, sort_keys=True))
        except TypeError as e:
            raise ConfigurationError(
                "Tools provided to create_cache() must be JSON serializable.",
                hint="If using custom objects or Pydantic models for tools, convert them to dicts first.",
            ) from e

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
    tools: list[dict[str, Any]] | list[Any] | None = None,
    ttl_seconds: int,
    retry_policy: RetryPolicy | None = None,
) -> tuple[str, float] | None:
    """Get existing cache or create new one with single-flight protection.

    Single-flight: concurrent requests for the same key share one creation call.
    """
    if not provider.capabilities.persistent_cache:
        return None

    async def _work() -> tuple[str, float]:
        logger.debug("Creating cache key=%s…", key[:8])
        if retry_policy is None or retry_policy.max_attempts <= 1:
            name = await provider.create_cache(
                model=model,
                parts=parts,
                system_instruction=system_instruction,
                tools=tools,
                ttl_seconds=ttl_seconds,
            )
            return name, time.time() + max(0, ttl_seconds)

        name = await retry_async(
            lambda: provider.create_cache(
                model=model,
                parts=parts,
                system_instruction=system_instruction,
                tools=tools,
                ttl_seconds=ttl_seconds,
            ),
            policy=retry_policy,
            should_retry=should_retry_side_effect,
        )
        return name, time.time() + max(0, ttl_seconds)

    return await singleflight_cached(
        key,
        lock=registry._lock,
        inflight=registry._inflight,
        cache_get=registry.get,
        cache_set=registry.set,
        work=_work,
    )
