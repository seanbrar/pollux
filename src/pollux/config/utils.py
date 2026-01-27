# src/pollux/config/utils.py

"""Configuration utilities and shared functionality.

This module contains pure utility functions that can be imported without
creating circular dependencies. It includes provider inference, path utilities,
and other configuration helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

# --- Provider Inference (Simplified & Pattern-Based) ---

# Provider patterns in priority order (checked first to last)
_PROVIDER_PATTERNS = [
    # Exact model names (highest priority)
    (r"^gemini-1\.5-flash$", "google"),
    (r"^gemini-1\.5-pro$", "google"),
    (r"^gpt-4o$", "openai"),
    (r"^claude-3-5-sonnet$", "anthropic"),
    # Version-aware patterns (medium priority)
    (r"^gemini-[0-9]+\.[0-9]+", "google"),
    (r"^gpt-[0-9]+", "openai"),
    (r"^claude-[0-9]+", "anthropic"),
    # Simple prefixes (fallback patterns)
    (r"^gemini-", "google"),
    (r"^gpt-", "openai"),
    (r"^claude-", "anthropic"),
]


@cache
def _compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile regex pattern with caching for performance."""
    return re.compile(pattern, re.IGNORECASE)


def resolve_provider(model: str) -> str:
    """Resolve provider from model name using pattern matching.

    Args:
        model: Model identifier string.

    Returns:
        Provider name (e.g., "google", "openai", "anthropic").
    """
    if not model:
        return "google"

    # Check patterns in priority order using cached compilation
    for pattern, provider in _PROVIDER_PATTERNS:
        if _compile_pattern(pattern).match(model):
            return provider

    return "google"  # Default fallback


# --- Path Utilities ---


def get_config_path(path_type: Literal["project", "home"]) -> Path:
    """Get configuration file path with environment override support.

    Robust to missing HOME in restricted environments by falling back to a
    cwd-based path for the "home" type when Path.home() cannot be resolved.
    """
    specs: dict[str, tuple[str, Callable[[], Path]]] = {
        "project": (
            PYPROJECT_PATH_VAR,
            lambda: Path.cwd() / "pyproject.toml",
        ),
        "home": (
            CONFIG_HOME_VAR,
            lambda: Path.home() / ".config" / "pollux.toml",
        ),
    }
    env_var, default_factory = specs[path_type]
    # Only respect the library's primary override variable for clarity
    if override := os.environ.get(env_var):
        return Path(override)
    try:
        return default_factory()
    except Exception:
        if path_type == "home":
            return Path.cwd() / "pollux.toml"
        raise


def get_pyproject_path() -> Path:
    """Return path to project pyproject.toml.

    Legacy function for backward compatibility.
    """
    return get_config_path("project")


def get_home_config_path() -> Path:
    """Return path to user's home-level config TOML.

    Legacy function for backward compatibility.
    """
    return get_config_path("home")


# --- Environment Utilities ---


# --- Constants ---

ENV_PREFIX = "POLLUX_"

CONFIG_HOME_VAR = "POLLUX_CONFIG_HOME"
PYPROJECT_PATH_VAR = "POLLUX_PYPROJECT_PATH"
PROFILE_VAR = "POLLUX_PROFILE"
DEBUG_CONFIG_VAR = "POLLUX_DEBUG_CONFIG"

# --- Environment Utilities ---


def get_effective_profile(*, env_first: bool = True) -> str | None:
    """Determine effective profile name, preferring env by default."""
    if env_first:
        return os.environ.get(PROFILE_VAR)
    return None


# --- Field Specification Helpers ---


def field_spec_hint(field: str) -> str:
    """Return a compact hint for setting a config field via env or files."""
    env_key = f"{ENV_PREFIX}{field.upper()}"
    return (
        f"Set {env_key} or [tool.pollux] {field} in pyproject.toml "
        "(or ~/.config/pollux.toml)."
    )


def should_emit_debug() -> bool:
    """Return True when debug audit is enabled via environment.

    This function is intentionally stateless for thread-safety. Callers should
    rely on Python's warnings machinery (default filtering prints once per
    location) to avoid repeated emissions across threads.
    """
    return os.environ.get(DEBUG_CONFIG_VAR, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


# --- Extra Fields Validation Patterns ---


@dataclass(frozen=True)
class ExtraFieldRule:
    """Rule for validating extra configuration fields."""

    pattern: str  # Field name pattern (regex)
    type_hint: type | str  # Expected type or type description
    description: str  # Human-readable description
    deprecated: bool = False  # Whether the field is deprecated


# Known extra field patterns for documentation and validation
KNOWN_EXTRA_FIELDS = (
    ExtraFieldRule(
        pattern=r"^.*_timeout$", type_hint=int, description="Timeout values in seconds"
    ),
    ExtraFieldRule(
        pattern=r"^.*_url$",
        type_hint=str,
        description="URL endpoints for external services",
    ),
    ExtraFieldRule(
        pattern=r"^experimental_.*",
        type_hint="Any",
        description="Experimental features (unstable API)",
    ),
    ExtraFieldRule(
        pattern=r"^legacy_.*",
        type_hint="Any",
        description="Legacy fields for backward compatibility",
        deprecated=True,
    ),
    ExtraFieldRule(
        pattern=r"^prompts\..*",
        type_hint="Any",
        description="Prompt assembly configuration",
    ),
)


def validate_extra_field(name: str, value: Any) -> list[str]:
    """Validate an extra field against known patterns.

    Returns list of warnings/suggestions, empty if valid.
    """
    messages: list[str] = []

    for rule in KNOWN_EXTRA_FIELDS:
        if re.match(rule.pattern, name):
            if rule.deprecated:
                messages.append(
                    f"Field '{name}' matches deprecated pattern: {rule.description}"
                )

            # Basic type checking for known patterns
            if isinstance(rule.type_hint, type) and not isinstance(
                value, rule.type_hint
            ):
                messages.append(
                    f"Field '{name}' expected {rule.type_hint.__name__}, "
                    f"got {type(value).__name__}"
                )
            break
    return messages


# --- Sensitive Key Utilities ---

# Field-level sensitive tokens used for redaction in audits and structured logs.
# Note: Environment-variable redaction uses a separate, looser heuristic and
# remains in core.check_environment to preserve DX expectations and tests.
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "access_key",
    "client_secret",
}


def is_sensitive_field_key(name: str) -> bool:
    """Return True if a field name is considered sensitive for logging."""
    lower = name.lower()
    return any(token in lower for token in SENSITIVE_KEYS)
