"""Validation of a planned interaction against provider capabilities.

This is the capability-resolution seam: given the requested ``Options`` and a
provider's ``ProviderCapabilities``, reject combinations the provider cannot
serve before any network I/O. Providers may still perform finer model-specific
validation at their boundary (see ``ValidatingProvider``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pollux.errors import ConfigurationError

if TYPE_CHECKING:
    from pollux.options import Options
    from pollux.providers.base import ProviderCapabilities


def validate_capabilities(
    options: Options,
    caps: ProviderCapabilities,
    *,
    n_prompts: int,
    has_file_parts: bool,
    cache_requested: bool,
) -> None:
    """Reject requested features the provider does not support.

    Args:
        options: Normalized execution options for the interaction.
        caps: The provider's declared capabilities.
        n_prompts: Number of prompts in the plan (conversation is single-prompt).
        has_file_parts: Whether the plan carries local file parts to upload.
        cache_requested: Whether a persistent cache handle is in play.

    Raises:
        ConfigurationError: If a requested feature is unsupported. Order is
            preserved so callers see a deterministic first failure.
    """
    wants_conversation = (
        options.history is not None or options.continue_from is not None
    )

    # Uniform "feature requested but provider lacks the capability" checks.
    # Each row: (requested, supported, message, hint).
    uniform_checks: tuple[tuple[bool, bool, str, str], ...] = (
        (
            options.response_schema is not None,
            caps.structured_outputs,
            "Provider does not support structured outputs",
            "Remove response_schema or choose a provider with schema support.",
        ),
        (
            options.reasoning_effort is not None,
            caps.reasoning,
            "Provider does not support reasoning controls",
            "Remove reasoning_effort or choose a provider with reasoning "
            "controls. Some providers may still surface model-native "
            "reasoning output without this option.",
        ),
        (
            options.reasoning_budget_tokens is not None,
            caps.reasoning_budget_tokens,
            "Provider does not support reasoning_budget_tokens",
            "Use reasoning_effort, or choose a provider that accepts "
            "an explicit reasoning token budget.",
        ),
        (
            options.implicit_caching is True,
            caps.implicit_caching,
            "Provider does not support implicit caching",
            "Remove implicit_caching=True or choose a provider with implicit "
            "caching support.",
        ),
        (
            wants_conversation,
            caps.conversation,
            "Provider does not support conversation continuity",
            "Remove history/continue_from or choose a provider with "
            "conversation support.",
        ),
    )
    for requested, supported, message, hint in uniform_checks:
        if requested and not supported:
            raise ConfigurationError(message, hint=hint)

    if wants_conversation and n_prompts != 1:
        raise ConfigurationError(
            "Conversation continuity currently supports exactly one prompt per call",
            hint="Use run() or run_many() with a single prompt when passing "
            "history/continue_from.",
        )

    # Runtime safety net: reject hand-built handles targeting providers that
    # lack persistent caching (the planner already validates other cache
    # conflicts).
    if cache_requested and not caps.persistent_cache:
        raise ConfigurationError(
            "Provider does not support persistent caching",
            hint=(
                "Remove options.cache or choose a provider with "
                "persistent_cache support."
            ),
        )

    if has_file_parts and not caps.uploads:
        raise ConfigurationError(
            "Provider does not support file or multimodal input",
            hint=caps.file_rejection_hint
            or "Choose a provider with uploads support, or remove file sources.",
        )
