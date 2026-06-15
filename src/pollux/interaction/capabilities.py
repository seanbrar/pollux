"""Resolve effective provider capabilities for the v2 interaction path.

A provider exposes static capabilities. A ``Config`` may additionally declare
capability overrides — to cap support a provider claims, or to assert support a
provider's static block omits (the local OpenAI-compatible server case). When the
two disagree, the user's declaration wins; undeclared capabilities fall back to
the provider's static value. The structural-protocol decomposition of capabilities
arrives with the Slice 3 boundary restructure; this is the additive seam.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from pollux.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from pollux.providers.base import ProviderCapabilities

#: Boolean capability fields a ``Config`` may declare. These mirror the boolean
#: fields of ``ProviderCapabilities``.
DECLARABLE_CAPABILITIES = (
    "persistent_cache",
    "uploads",
    "structured_outputs",
    "reasoning",
    "reasoning_budget_tokens",
    "deferred_delivery",
    "conversation",
    "implicit_caching",
)


def resolve_capabilities(
    static: ProviderCapabilities,
    declared: Mapping[str, bool] | None,
) -> ProviderCapabilities:
    """Return the effective capabilities, applying ``Config`` declarations.

    Raises:
        ConfigurationError: If a declared capability name is unknown or its value
            is not a boolean. Raised before any network I/O.
    """
    if not declared:
        return static

    # Typed Any so dataclasses.replace accepts the splat across mixed field types.
    overrides: dict[str, Any] = {}
    for name, value in declared.items():
        if name not in DECLARABLE_CAPABILITIES:
            allowed = ", ".join(DECLARABLE_CAPABILITIES)
            raise ConfigurationError(
                f"Unknown capability declaration: {name!r}",
                hint=f"Declarable capabilities are: {allowed}.",
            )
        if not isinstance(value, bool):
            raise ConfigurationError(
                f"Capability declaration {name!r} must be a boolean",
                hint="Pass capabilities={'structured_outputs': True}.",
            )
        overrides[name] = value

    return replace(static, **overrides)
