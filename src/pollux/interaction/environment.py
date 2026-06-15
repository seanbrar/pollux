"""``Environment`` and ``EnvironmentSnapshot``: the reusable model-facing setup.

An :class:`Environment` is the stable context around one or more interactions:
instructions, sources, tool declarations, and a cache preference. It does not
contain conversation history or application memory. An
:class:`EnvironmentSnapshot` is the planned, immutable provider-facing form whose
``fingerprint`` backs continuation and cache compatibility checks.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pollux.interaction.tools import ToolDeclaration
    from pollux.source import Source


@dataclass(frozen=True, slots=True)
class CachePolicy:
    """An explicit persistent-cache preference for an environment."""

    ttl_seconds: int | None = None


#: ``"auto"`` opts into provider-managed caching; ``"none"`` disables it.
CacheSetting = CachePolicy | Literal["auto", "none"] | None


@dataclass(frozen=True, slots=True)
class Environment:
    """The reusable, stable model-facing setup around interactions.

    ``sources`` and ``tools`` accept any ordered sequence and are frozen to
    tuples. Tool declarations must be :class:`ToolDeclaration` objects; the
    friendly facades (Slice 3) coerce raw dict schemas through
    :meth:`ToolDeclaration.from_dict`.
    """

    instructions: str | None = None
    sources: Sequence[Source] = ()
    tools: Sequence[ToolDeclaration] = ()
    cache: CacheSetting = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Freeze the source and tool sequences to immutable tuples."""
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "tools", tuple(self.tools))


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    """The planned, immutable provider-facing environment for one interaction."""

    instructions: str | None = None
    sources: tuple[Source, ...] = ()
    tools: tuple[ToolDeclaration, ...] = ()
    cache: CacheSetting = None
    provider: str | None = None

    def fingerprint(self) -> str:
        """Return a stable hash of the provider-facing environment identity.

        Used to reject reuse of a continuation or cache handle against an
        environment whose instructions, sources, or tools have changed.
        """
        payload = {
            "instructions": self.instructions,
            "sources": [
                source.cache_identity_hash(provider=self.provider)
                for source in self.sources
            ],
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
                for tool in self.tools
            ],
            "cache": _cache_fingerprint(self.cache),
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_environment(
        cls, environment: Environment, *, provider: str | None = None
    ) -> EnvironmentSnapshot:
        """Freeze an :class:`Environment` into a provider-facing snapshot."""
        return cls(
            instructions=environment.instructions,
            sources=tuple(environment.sources),
            tools=tuple(environment.tools),
            cache=environment.cache,
            provider=provider,
        )


def _cache_fingerprint(cache: CacheSetting) -> Any:
    """Reduce a cache setting to a JSON-stable fingerprint component."""
    if isinstance(cache, CachePolicy):
        return {"ttl_seconds": cache.ttl_seconds}
    return cache
