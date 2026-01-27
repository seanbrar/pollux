# src/pollux/config/__init__.py

"""Configuration management for the Gemini Batch Pipeline.

This module provides the new Pydantic Two-File Core configuration system
that replaces the previous multi-file approach with a clean, data-centric design.

The core principle is resolve-once, freeze-then-flow: configuration is resolved
at entry points into immutable FrozenConfig objects that flow through the pipeline.

Key exports:
- resolve_config: Main API for configuration resolution
- FrozenConfig: Immutable configuration payload for pipeline
- config_scope: Context manager for scoped configuration
- Settings: Pydantic schema for validation and defaults
"""

# ruff: noqa: I001

# --- Core Configuration API ---

from .core import (
    FrozenConfig,
    Origin,
    FieldOrigin,
    Settings,
    SourceMap,
    was_field_overridden,
    tier_was_specified,
    to_redacted_dict,
    audit_layers_summary,
    audit_lines,
    audit_text,
    summarize_origins,
    doctor,
    check_environment,
    config_scope,
    resolve_config,
)

# Re-export key functions from loaders and utils for advanced usage
from .loaders import list_profiles, validate_profile, profile_validation_error
from .utils import (
    resolve_provider,
    get_effective_profile,
    field_spec_hint,
)

__all__ = [  # noqa: RUF022
    # Main public API
    "resolve_config",
    "FrozenConfig",
    "config_scope",
    # Core types for typing and advanced usage
    "Settings",
    "Origin",
    "FieldOrigin",
    "SourceMap",
    # Provenance helpers
    "was_field_overridden",
    "tier_was_specified",
    "field_spec_hint",
    # Redacted view & summaries
    "to_redacted_dict",
    "audit_layers_summary",
    # Audit helpers
    "audit_lines",
    "audit_text",
    "summarize_origins",
    "doctor",
    "check_environment",
    # ambient removed; prefer explicit `config_scope` and `resolve_config`
    # Advanced utilities
    "resolve_provider",
    "list_profiles",
    "get_effective_profile",
    "validate_profile",
    "profile_validation_error",
]
