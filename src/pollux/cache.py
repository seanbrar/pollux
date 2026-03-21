"""Cache: Content-hash identity with expires_at tracking."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any

from pollux._singleflight import singleflight_cached
from pollux.errors import ConfigurationError, InternalError
from pollux.retry import RetryPolicy, retry_async, should_retry_side_effect

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pollux.config import Config
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
    api_key: str | None = None,
    system_instruction: str | None = None,
    tools: list[dict[str, Any]] | list[Any] | None = None,
) -> str:
    """Compute deterministic cache key using source identity hashes.

    Key = hash(model + provider + api_key + system + source identity digests).
    Including ``api_key`` prevents cross-account handle reuse when multiple keys
    for the same provider/model coexist in one process.
    """
    parts = [model]
    if provider:
        parts.append(provider)
    if api_key:
        parts.append(api_key)
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
        parts.append(source.cache_identity_hash(provider=provider))

    combined = "|".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


async def get_or_create_cache(
    provider: Provider,
    registry: CacheRegistry,
    *,
    key: str,
    model: str,
    raw_parts: list[Any],
    system_instruction: str | None,
    tools: list[dict[str, Any]] | list[Any] | None = None,
    ttl_seconds: int,
    retry_policy: RetryPolicy | None = None,
) -> tuple[str, float] | None:
    """Get existing cache or create new one with single-flight protection.

    File placeholders in *raw_parts* are resolved inside the single-flight
    work function so concurrent callers share both uploads and cache creation.
    """
    if not provider.capabilities.persistent_cache:
        return None

    async def _work() -> tuple[str, float]:
        logger.debug("Creating cache key=%s…", key[:8])
        policy = retry_policy or RetryPolicy(max_attempts=1)
        parts = await _resolve_file_parts(raw_parts, provider, policy)
        if policy.max_attempts <= 1:
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
            policy=policy,
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


# Module-level registry shared across create_cache calls.
_registry = CacheRegistry()


async def _resolve_file_parts(
    parts: list[Any],
    provider: Provider,
    retry_policy: RetryPolicy,
) -> list[Any]:
    """Replace file placeholders with uploaded assets.

    Memoizes by ``(file_path, mime_type)`` so duplicate file sources in a
    single ``create_cache()`` call share one upload.  No singleflight
    needed because ``create_cache`` is sequential, not concurrent fan-out.
    """
    resolved: list[Any] = []
    seen: dict[tuple[str, str], Any] = {}
    for part in parts:
        if (
            isinstance(part, dict)
            and isinstance(part.get("file_path"), str)
            and isinstance(part.get("mime_type"), str)
        ):
            fp, mt = part["file_path"], part["mime_type"]
            provider_hints = part.get("provider_hints")
            key = (fp, mt)
            if key in seen:
                asset = seen[key]
            else:
                if retry_policy.max_attempts <= 1:
                    asset = await provider.upload_file(Path(fp), mt)
                else:

                    async def _upload(_fp: str = fp, _mt: str = mt) -> Any:
                        return await provider.upload_file(Path(_fp), _mt)

                    asset = await retry_async(
                        _upload,
                        policy=retry_policy,
                        should_retry=should_retry_side_effect,
                    )
                seen[key] = asset
            if provider_hints is not None:
                resolved.append(
                    {
                        "uri": asset.file_id,
                        "mime_type": mt,
                        "provider_hints": provider_hints,
                    }
                )
            else:
                resolved.append(asset)
        else:
            resolved.append(part)
    return resolved


async def create_cache_impl(
    sources: Sequence[Source],
    *,
    provider: Provider,
    config: Config,
    system_instruction: str | None = None,
    tools: list[dict[str, Any]] | list[Any] | None = None,
    ttl_seconds: int = 3600,
) -> CacheHandle:
    """Core implementation of ``create_cache()``.

    Receives an already-initialized provider; the caller manages its lifecycle.

    All input validation is intentionally front-loaded before any I/O
    (uploads, API calls).  If the parameter surface grows beyond the
    current five axes, consider a validated ``CacheSpec`` dataclass to
    keep this boundary manageable.
    """
    from pollux.plan import build_shared_parts
    from pollux.source import Source as SourceCls

    if not isinstance(ttl_seconds, int) or ttl_seconds < 1:
        raise ConfigurationError(
            f"ttl_seconds must be an integer ≥ 1, got {ttl_seconds!r}",
            hint="Pass a positive integer for the cache TTL.",
        )

    if system_instruction is not None and not isinstance(system_instruction, str):
        raise ConfigurationError(
            f"system_instruction must be a string, got {type(system_instruction).__name__}",
            hint="Pass a string for the system instruction.",
        )

    if not provider.capabilities.persistent_cache:
        raise ConfigurationError(
            f"Provider {config.provider!r} does not support persistent caching",
            hint="Use a provider that supports persistent_cache (e.g. Gemini).",
        )

    src_tuple = tuple(sources) if not isinstance(sources, tuple) else sources

    for s in src_tuple:
        if not isinstance(s, SourceCls):
            raise ConfigurationError(
                f"Expected Source, got {type(s).__name__}",
                hint="Use Source.from_file(), Source.from_text(), etc.",
            )

    if tools is not None:
        for i, t in enumerate(tools):
            if not isinstance(t, dict):
                raise ConfigurationError(
                    f"Tool at index {i} must be a dictionary, got {type(t).__name__}",
                    hint="Ensure all items in the tools list are dictionaries.",
                )

    key = compute_cache_key(
        config.model,
        src_tuple,
        provider=config.provider,
        api_key=config.api_key,
        system_instruction=system_instruction,
        tools=tools,
    )

    cached = _registry.get(key)
    if cached is not None:
        cache_name, expires_at = cached
        return CacheHandle(
            name=cache_name,
            model=config.model,
            provider=config.provider,
            expires_at=expires_at,
        )

    raw_parts = build_shared_parts(src_tuple, provider=config.provider)

    result = await get_or_create_cache(
        provider,
        _registry,
        key=key,
        model=config.model,
        raw_parts=raw_parts,
        system_instruction=system_instruction,
        tools=tools,
        ttl_seconds=ttl_seconds,
        retry_policy=config.retry,
    )

    if result is None:
        raise InternalError(
            "Cache creation returned None unexpectedly",
            hint="This is a Pollux internal error. Please report it.",
        )

    cache_name, expires_at = result

    return CacheHandle(
        name=cache_name,
        model=config.model,
        provider=config.provider,
        expires_at=expires_at,
    )
