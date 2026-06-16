"""Validate a planned v2 interaction against provider capabilities.

Reads the v2 primitives (``OutputRequirements`` / ``Input`` /
``EnvironmentSnapshot``) and rejects requested features the provider cannot serve
before any network I/O. Fine-grained capabilities still use the
``ProviderCapabilities`` booleans; the structural-protocol decomposition is a
later Slice 2 sub-PR.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pollux.errors import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pollux.interaction.environment import EnvironmentSnapshot
    from pollux.interaction.input import Input
    from pollux.interaction.requirements import OutputRequirements
    from pollux.providers.base import ProviderCapabilities


def _wants_conversation(inputs: Sequence[Input]) -> bool:
    """Whether any input continues a prior turn via continuation or history."""
    return any(
        inp.continuation is not None or inp.history is not None for inp in inputs
    )


def validate_interaction(
    requirements: OutputRequirements,
    inputs: Sequence[Input],
    snapshot: EnvironmentSnapshot,
    caps: ProviderCapabilities,
    *,
    cache_requested: bool,
) -> None:
    """Reject requested features the provider does not support.

    Raises:
        ConfigurationError: If a requested feature is unsupported. Order is
            preserved so callers see a deterministic first failure.
    """
    wants_conversation = _wants_conversation(inputs)

    uniform_checks: tuple[tuple[bool, bool, str, str], ...] = (
        (
            requirements.output_schema is not None,
            caps.structured_outputs,
            "Provider does not support structured outputs",
            "Remove output_schema or choose a provider with schema support.",
        ),
        (
            requirements.reasoning_effort is not None,
            caps.reasoning,
            "Provider does not support reasoning controls",
            "Remove reasoning_effort or choose a provider with reasoning controls.",
        ),
        (
            requirements.reasoning_budget_tokens is not None,
            caps.reasoning_budget_tokens,
            "Provider does not support reasoning_budget_tokens",
            "Use reasoning_effort, or choose a provider that accepts an explicit "
            "reasoning token budget.",
        ),
        (
            wants_conversation,
            caps.conversation,
            "Provider does not support conversation continuity",
            "Remove continuation/history or choose a provider with conversation "
            "support.",
        ),
    )
    for requested, supported, message, hint in uniform_checks:
        if requested and not supported:
            raise ConfigurationError(message, hint=hint)

    if wants_conversation and len(inputs) != 1:
        raise ConfigurationError(
            "Conversation continuity currently supports exactly one input per call",
            hint="Continue from a single input when passing continuation/history.",
        )

    if cache_requested and not caps.persistent_cache:
        raise ConfigurationError(
            "Provider does not support persistent caching",
            hint="Remove the cache policy or choose a provider with "
            "persistent_cache support.",
        )

    has_file_sources = any(source.source_type == "file" for source in snapshot.sources)
    if has_file_sources and not caps.uploads:
        raise ConfigurationError(
            "Provider does not support file or multimodal input",
            hint=caps.file_rejection_hint
            or "Choose a provider with uploads support, or remove file sources.",
        )
