"""``Environment`` and ``EnvironmentSnapshot``: the reusable model-facing setup.

An :class:`Environment` is the stable context around one or more interactions:
instructions, sources, tool declarations, and a cache preference. It does not
contain conversation history or application memory. An
:class:`EnvironmentSnapshot` is the internal, planned, immutable provider-facing
form used by the execution path.
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


_FINGERPRINT_VERSION = 1


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
    tuples. Tool declarations must be :class:`ToolDeclaration` objects; build one
    from a raw dict schema with :meth:`ToolDeclaration.from_dict`.
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

    def fingerprint(self, *, provider: str) -> str:
        """Return stable identity for the provider-visible environment.

        The fingerprint covers instructions, ordered sources, ordered tools,
        and the active provider. Model identity belongs to :class:`Config` and
        must be composed separately by durable runtimes. Cache preferences and
        metadata are deliberately excluded because they do not change the
        model-visible environment.

        Fingerprints remain stable across compatible Pollux releases. A future
        semantic change will increment the embedded fingerprint version.
        """
        if not isinstance(provider, str) or not provider:
            from pollux.errors import ConfigurationError

            raise ConfigurationError(
                "Environment fingerprint requires a non-empty provider",
                hint="Pass config.provider when creating durable identity.",
            )
        payload = {
            "version": _FINGERPRINT_VERSION,
            "provider": provider,
            "instructions": self.instructions,
            "sources": [
                source._environment_identity(provider=provider)
                for source in self.sources
            ],
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                    "strict": tool.strict,
                }
                for tool in self.tools
            ],
        }
        try:
            encoded = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            from pollux.errors import ConfigurationError

            raise ConfigurationError(
                "Environment identity is not JSON serializable",
                hint="Use JSON-compatible tool schemas and provider hints.",
            ) from exc
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    """The planned, immutable provider-facing environment for one interaction.

    ``instructions``/``sources``/``tools``/``cache``/``provider`` describe the
    planned request. The remaining fields are core-populated transport state,
    frozen onto the snapshot by the execution path just before
    ``Provider.generate`` so adapters compile from primitives:

    - ``prepared_parts``: the environment's shared source parts with local files
      already uploaded (single-flight, once per fan-out); empty when a persistent
      cache bakes the sources in.
    - ``cache_name``: the resolved provider persistent-cache name, if any.
    - ``implicit_caching``: whether provider-managed implicit caching is enabled.

    Applications use :meth:`Environment.fingerprint` for durable identity; the
    snapshot is an internal planning type.
    """

    instructions: str | None = None
    sources: tuple[Source, ...] = ()
    tools: tuple[ToolDeclaration, ...] = ()
    cache: CacheSetting = None
    provider: str | None = None
    prepared_parts: tuple[Any, ...] | None = None
    cache_name: str | None = None
    implicit_caching: bool = False

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
