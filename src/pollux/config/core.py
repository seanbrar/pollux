# src/pollux/config/core.py

"""Core configuration schema and resolution for Gemini Batch Pipeline.

This module implements the Pydantic Two-File Core design that provides:
- Single source of truth for configuration schema (Settings)
- Immutable runtime payload (FrozenConfig)
- Pure data resolution with audit tracking (SourceMap)
- Guarded ambient scope for entry-time convenience
"""

from __future__ import annotations

from contextlib import contextmanager, suppress
import contextvars
from dataclasses import dataclass
from enum import Enum
from functools import cache
import os
from typing import TYPE_CHECKING, Any, Literal, overload
import warnings

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from pollux.core.exceptions import HINTS, ConfigurationError
from pollux.core.models import APITier

from .utils import field_spec_hint, is_sensitive_field_key, should_emit_debug

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping
    from types import TracebackType

# --- Schema (Pydantic wall) ---


class Settings(BaseModel):
    """Pydantic settings schema for configuration validation and defaults.

    This is the single source of truth for configuration fields, types,
    defaults, and validation rules. All configuration resolution flows
    through this schema wall to ensure data integrity.
    """

    # Core fields
    model: str = Field(default="gemini-2.0-flash", min_length=1)
    # Accept plain strings or SecretStr, normalize to SecretStr | None
    api_key: SecretStr | str | None = Field(default=None)
    use_real_api: bool = Field(default=False)

    # Caching and performance
    enable_caching: bool = Field(default=False)
    # Non-negative TTL using Field constraint (replaces custom validator)
    ttl_seconds: int = Field(default=3600, ge=0)

    # Telemetry and billing
    telemetry_enabled: bool = Field(default=False)
    tier: APITier = Field(default=APITier.FREE)
    # Concurrency defaults (client-side fan-out bounds)
    request_concurrency: int = Field(default=6, ge=0)

    model_config = {"extra": "allow"}  # Preserve unknown keys for extensibility

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, v: Any) -> Any:
        """Trim surrounding whitespace on model identifiers."""
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, v: Any) -> Any:
        """Normalize api_key: trim whitespace, map empty to None, wrap in SecretStr."""
        if v is None:
            return None
        if isinstance(v, SecretStr):
            # Normalize wrapped value
            s = v.get_secret_value().strip()
            return SecretStr(s) if s else None
        if isinstance(v, str):
            s = v.strip()
            return SecretStr(s) if s else None
        return v

    @field_validator("tier", mode="before")
    @classmethod
    def normalize_tier(cls, v: Any) -> Any:
        """Accept enum values or common string forms for tier.

        Supports enum instance, exact value (e.g., "free"), or enum name ("FREE").
        """
        if v is None or isinstance(v, APITier):
            return v or APITier.FREE

        # Handle string values (by value then by name)
        if isinstance(v, str):
            v = v.strip()
            with suppress(ValueError):
                return APITier(v)
            with suppress(KeyError):
                return APITier[v.upper()]

        return v  # Let Pydantic raise with a precise error message

    @field_validator("ttl_seconds", mode="before")
    @classmethod
    def validate_ttl_nonnegative(cls, v: Any) -> Any:
        """Preserve friendly error message while also using Field(ge=0)."""
        try:
            iv = int(v)
        except Exception:
            return v
        if iv < 0:
            raise ValueError("ttl_seconds must be >= 0")
        return v

    @model_validator(mode="after")
    def validate_api_key_required_if_real_api(self) -> Settings:
        """Validate that API key is provided when use_real_api=True."""
        if self.use_real_api and self.api_key is None:
            raise ValueError("api_key is required when use_real_api=True")
        return self


# Cache default settings to avoid repeated Pydantic instantiation per resolution.
@cache
def _default_settings() -> dict[str, Any]:
    return Settings().model_dump()


# --- Immutable runtime payload ---


@dataclass(frozen=True)
class FrozenConfig:
    """Immutable configuration payload passed through the pipeline.

    This represents the final, validated configuration state with provider
    inference applied. It flows through pipeline handlers as the single
    source of configuration truth during execution.
    """

    model: str
    api_key: str | None
    use_real_api: bool
    enable_caching: bool
    ttl_seconds: int
    telemetry_enabled: bool
    tier: APITier
    provider: str
    extra: Mapping[str, Any]
    # Client-side fan-out default for vectorized API calls
    request_concurrency: int

    def __str__(self) -> str:
        """String representation with redacted API key for safe logging."""
        # Create field representation with selective redaction
        fields = []
        for field in self.__dataclass_fields__:
            value = getattr(self, field)
            if field == "api_key" and value:
                fields.append(f"{field}='[REDACTED]'")
            elif field == "extra":
                continue  # Skip extra fields in summary representation
            else:
                fields.append(f"{field}={value!r}")

        return f"FrozenConfig({', '.join(fields)})"

    __repr__ = __str__  # Direct assignment for identical behavior


# --- Audit types ---


class Origin(str, Enum):
    """Source origin for configuration field values."""

    DEFAULT = "default"
    HOME = "home"
    PROJECT = "project"
    ENV = "env"
    OVERRIDES = "overrides"


@dataclass(frozen=True)
class FieldOrigin:
    """Tracks the origin and context of a configuration field value."""

    origin: Origin
    env_key: str | None = None  # e.g., "GEMINI_API_KEY"
    file: str | None = None  # e.g., "~/.config/pollux.toml"


SourceMap = dict[str, FieldOrigin]


# --- Ambient scope (guarded) ---

_AMBIENT: contextvars.ContextVar[FrozenConfig | None] = contextvars.ContextVar(
    "ambient_config", default=None
)

_DOTENV_LOADED: bool = False


class ConfigScope:
    """Context manager for temporarily setting ambient configuration.

    This provides scoped configuration for entry-time convenience while
    maintaining the principle that pipeline code should receive explicit
    FrozenConfig instances.
    """

    def __init__(self, cfg: FrozenConfig):
        """Initialize the context manager with a configuration."""
        self._token: contextvars.Token[FrozenConfig | None] | None = None
        self._cfg = cfg

    def __enter__(self) -> FrozenConfig:
        """Enter the context and set ambient configuration."""
        self._token = _AMBIENT.set(self._cfg)
        return self._cfg

    def __exit__(
        self,
        _: type[BaseException] | None,
        __: BaseException | None,
        ___: TracebackType | None,
    ) -> Literal[False]:
        """Exit the context and restore previous ambient configuration."""
        if self._token is not None:
            _AMBIENT.reset(self._token)
        return False


@contextmanager
def config_scope(
    cfg_or_overrides: Mapping[str, Any] | FrozenConfig | None = None,
    *,
    profile: str | None = None,
    **overrides: object,
) -> Generator[FrozenConfig]:
    """Create a scoped configuration context.

    This context manager allows running operations with specific configuration
    without affecting global state. It's thread-safe and async-safe.

    Args:
        cfg_or_overrides: Either a FrozenConfig to use directly, or a mapping
            of overrides to apply during resolution.
        profile: Optional profile name used when resolving from files within
            this scope (passed to TOML loaders).
        **overrides: Additional override values (merged with cfg_or_overrides
            if it's a mapping).

    Yields:
        The FrozenConfig instance active in this scope.

    Example:
        with config_scope({"model": "gemini-2.0-pro", "use_real_api": True}):
            # Code here uses the specified configuration
            executor = create_executor()
            result = await executor.execute(...)
    """
    if isinstance(cfg_or_overrides, FrozenConfig):
        cfg = cfg_or_overrides
    else:
        # Delegate to resolve_config with combined overrides
        combined_overrides = {**(cfg_or_overrides or {}), **overrides}
        cfg = resolve_config(overrides=combined_overrides, profile=profile)

    with ConfigScope(cfg):
        yield cfg


def _try_load_dotenv() -> None:
    """Try to load a .env file using python-dotenv if available.

    This is intentionally tolerant: absence of the dependency or errors
    during loading are ignored so that configuration resolution remains
    predictable in minimal environments.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        # Deliberately ignore any errors; dotenv is optional
        _DOTENV_LOADED = True
        return
    _DOTENV_LOADED = True


# --- Public resolution API ---


@overload
def resolve_config(
    overrides: Mapping[str, Any] | None = ...,
    profile: str | None = ...,
    *,
    explain: Literal[True],
) -> tuple[FrozenConfig, SourceMap]: ...


@overload
def resolve_config(
    overrides: Mapping[str, Any] | None = ...,
    profile: str | None = ...,
    *,
    explain: Literal[False] = ...,
) -> FrozenConfig: ...


def resolve_config(
    overrides: Mapping[str, Any] | None = None,
    profile: str | None = None,
    *,
    explain: bool = False,
) -> FrozenConfig | tuple[FrozenConfig, SourceMap]:
    """Resolve configuration from all sources into a FrozenConfig.

    This is the main public API for configuration resolution. It follows
    the precedence: defaults < home < project < env < overrides.

    Args:
        overrides: Programmatic configuration overrides.
        profile: Configuration profile name to use from TOML files.
        explain: If True, return tuple of (config, source_map) for audit.

    Returns:
        FrozenConfig instance, or tuple of (FrozenConfig, SourceMap) if explain=True.

    Raises:
        ConfigurationError: If configuration validation fails.
    """
    # Ensure .env is loaded (optional) before reading environment variables
    _try_load_dotenv()

    from . import utils as _utils
    from .loaders import load_env, load_home, load_pyproject

    # Compute effective profile once for deterministic resolution
    effective_profile = (
        profile if profile is not None else _utils.get_effective_profile()
    )

    merged, sources = _resolve_layers(
        overrides=overrides or {},
        env=load_env(),
        project=load_pyproject(profile=effective_profile),
        home=load_home(profile=effective_profile),
    )

    try:
        settings = Settings.model_validate(merged)
        frozen = _freeze(settings, merged)
    except ValidationError as e:
        # Extract first error for clarity
        err = e.errors()[0]
        msg = err.get("msg")
        # Remove "Value error, " prefix if present (Pydantic standard wrapper)
        if msg and msg.startswith("Value error, "):
            msg = msg[13:]

        # Map known errors to hints
        hint = None
        if "api_key is required" in (msg or ""):
            hint = HINTS["missing_api_key"]

        raise ConfigurationError(
            f"Configuration validation failed: {msg}", hint=hint
        ) from e
    # Note: Python's warnings filter prints once per callsite by default,
    # so we intentionally avoid global state and rely on that behavior.
    if not explain and should_emit_debug():
        # Intentionally ignore any emission errors to keep resolution robust
        with suppress(Exception):
            warnings.warn(
                "Config audit (redacted)\n" + "\n".join(audit_lines(frozen, sources)),
                stacklevel=2,
            )

    return (frozen, sources) if explain else frozen


# --- Internal helpers (pure & tiny) ---


def _freeze(settings: Settings, merged: Mapping[str, Any]) -> FrozenConfig:
    """Convert validated Settings to immutable FrozenConfig.

    Args:
        settings: Validated Pydantic settings instance.
        merged: Original merged data for extracting extras.

    Returns:
        FrozenConfig with known fields and preserved extras.
    """
    # Inline provider resolution for better encapsulation
    from .utils import resolve_provider

    provider = resolve_provider(settings.model)

    # Get only the known schema fields (exclude extras)
    # Derive known fields from schema to avoid drift
    known_fields = set(Settings.model_fields.keys())

    # Extract extra fields that aren't part of our schema
    extra = {k: v for k, v in merged.items() if k not in known_fields}

    # Validate extra fields for better developer experience
    _validate_extra_fields(extra)

    # Unwrap SecretStr -> plain string for runtime FrozenConfig API
    api_key_value: str | None
    if settings.api_key is None:
        api_key_value = None
    elif isinstance(settings.api_key, SecretStr):
        api_key_value = settings.api_key.get_secret_value()
    else:
        api_key_value = str(settings.api_key)

    return FrozenConfig(
        provider=provider,
        extra=extra,
        model=settings.model,
        api_key=api_key_value,
        use_real_api=settings.use_real_api,
        enable_caching=settings.enable_caching,
        ttl_seconds=settings.ttl_seconds,
        telemetry_enabled=settings.telemetry_enabled,
        tier=settings.tier,
        request_concurrency=settings.request_concurrency,
    )


def _validate_extra_fields(extra: Mapping[str, Any]) -> None:
    """Validate extra fields and emit warnings for common issues.

    This provides helpful feedback without breaking the configuration,
    following the principle of graceful degradation.
    """
    if not extra:
        return

    from .utils import validate_extra_field

    for name, value in extra.items():
        warnings_list = validate_extra_field(name, value)
        for warning_msg in warnings_list:
            warnings.warn(f"Configuration: {warning_msg}", UserWarning, stacklevel=3)


def _resolve_layers(
    *,
    overrides: Mapping[str, Any],
    env: Mapping[str, Any],
    project: Mapping[str, Any],
    home: Mapping[str, Any],
) -> tuple[dict[str, Any], SourceMap]:
    """Resolve configuration layers into merged dict and source tracking.

    This performs pure data merging with last-wins precedence while building
    an audit trail of where each field value originated.

    Args:
        overrides: Programmatic overrides (highest precedence).
        env: Environment variable values.
        project: Values from pyproject.toml.
        home: Values from user's home config file.

    Returns:
        Tuple of (merged_config_dict, source_map).
    """
    layers = [
        (Origin.HOME, home),
        (Origin.PROJECT, project),
        (Origin.ENV, env),
        (Origin.OVERRIDES, overrides),
    ]

    out: dict[str, Any] = {}
    src: SourceMap = {}

    # Start with defaults from Settings schema
    defaults = dict(_default_settings())
    for k, v in defaults.items():
        out[k] = v
        src[k] = FieldOrigin(origin=Origin.DEFAULT)

    def record(k: str, v: Any, origin: Origin) -> None:
        """Record a field value and its origin."""
        out[k] = v

        # Add contextual hints for audit reporting
        hints = {}
        if origin is Origin.ENV:
            import os

            from .utils import ENV_PREFIX

            # Attribute to specific env var used when possible.
            if k == "api_key":
                if f"{ENV_PREFIX}API_KEY" in os.environ:
                    hints["env_key"] = f"{ENV_PREFIX}API_KEY"
                elif "GEMINI_API_KEY" in os.environ:
                    hints["env_key"] = "GEMINI_API_KEY"
                else:
                    hints["env_key"] = f"{ENV_PREFIX}API_KEY"
            else:
                hints["env_key"] = f"{ENV_PREFIX}{k.upper()}"
        elif origin is Origin.PROJECT:
            from .utils import get_pyproject_path

            hints["file"] = str(get_pyproject_path())
        elif origin is Origin.HOME:
            from .utils import get_home_config_path

            hints["file"] = str(get_home_config_path())

        src[k] = FieldOrigin(origin=origin, **hints)

    # Apply layers in precedence order
    for origin, payload in layers:
        for k, v in payload.items():
            record(k, v, origin)

    return out, src


# --- Minimal audit helpers (transparency with small surface) ---


def _origin_label(field: str, where: FieldOrigin) -> str:
    match where.origin:
        case Origin.ENV:
            from .utils import ENV_PREFIX

            key = where.env_key or f"{ENV_PREFIX}{field.upper()}"
            return f"env:{key}"
        case Origin.PROJECT:
            file = where.file or "pyproject.toml"
            return f"file:{file}"
        case Origin.HOME:
            file = where.file or "~/.config/pollux.toml"
            return f"file:{file}"
        case _:
            return str(where.origin.value)


def audit_lines(cfg: FrozenConfig, sources: SourceMap) -> list[str]:
    """Produce redacted, human-readable audit lines per field.

    Only origins are shown; secrets are never printed.
    Includes a derived line for provider.
    """
    order = (
        "api_key",
        "model",
        "tier",
        "use_real_api",
        "enable_caching",
        "ttl_seconds",
        "telemetry_enabled",
    )
    lines: list[str] = []
    for field in order:
        fo = sources.get(field)
        if fo is None:
            continue
        # Append explicit redaction indicator for sensitive fields without ever printing values
        redaction = " [REDACTED]" if is_sensitive_field_key(field) else ""
        lines.append(f"{field}: {_origin_label(field, fo)}{redaction}")
    # Extras
    extra_keys = sorted(k for k in cfg.extra if k in sources)
    for k in extra_keys:
        redaction = " [REDACTED]" if is_sensitive_field_key(k) else ""
        lines.append(f"{k}: {_origin_label(k, sources[k])}{redaction}")
    # Derived line for provider
    lines.append("provider: derived:model")
    return lines


def audit_text(cfg: FrozenConfig, sources: SourceMap) -> str:
    """Format audit as a single string suitable for printing/logging."""
    return "\n".join(audit_lines(cfg, sources))


def summarize_origins(sources: SourceMap) -> dict[str, int]:
    """Count how many fields originated from each layer."""
    counts: dict[str, int] = {}
    for fo in sources.values():
        key = fo.origin.value
        counts[key] = counts.get(key, 0) + 1
    return counts


# --- Provenance helpers (tiny & generic) ---


def was_field_overridden(sources: SourceMap, field: str) -> bool:
    """Return True if a field's value did not come from defaults.

    This helper enables small, opt-in UX improvements (e.g., gentle suggestions)
    without polluting the immutable runtime payload with audit concerns.
    """
    fo = sources.get(field)
    return bool(fo and fo.origin is not Origin.DEFAULT)


def tier_was_specified(sources: SourceMap) -> bool:
    """Convenience wrapper for checking if 'tier' was provided by user sources."""
    return was_field_overridden(sources, "tier")


# --- DX sugar and diagnostics ---


def check_environment() -> dict[str, str]:
    """Return current GEMINI_* and POLLUX_* variables (redacted).

    DX helper: lists both the library domain and official provider variables to
    aid troubleshooting. Values that look like secrets are redacted.

    Returns:
        Mapping of variable names to string values (secrets redacted).
    """
    from .utils import ENV_PREFIX

    out: dict[str, str] = {}
    for k, v in os.environ.items():
        if not (k.startswith((ENV_PREFIX, "GEMINI_"))):
            continue
        is_secret = any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET"))
        out[k] = "***redacted***" if is_secret else v
    return out


# --- Redacted serialization and layer summary / doctor ---

# Sensitive field tokens centralized in utils


def to_redacted_dict(cfg: FrozenConfig) -> dict[str, Any]:
    """Redacted dict for structured logging (never prints secrets)."""

    def _redact(k: str, v: Any) -> Any:
        return "***redacted***" if is_sensitive_field_key(k) else v

    return {
        "model": cfg.model,
        "api_key": _redact("api_key", cfg.api_key),
        "use_real_api": cfg.use_real_api,
        "enable_caching": cfg.enable_caching,
        "ttl_seconds": cfg.ttl_seconds,
        "telemetry_enabled": cfg.telemetry_enabled,
        # Prefer Enum value for consistency and readability
        "tier": (cfg.tier.value if hasattr(cfg.tier, "value") else None)
        if cfg.tier is not None
        else None,
        "provider": cfg.provider,
        "extra": {k: _redact(k, v) for k, v in dict(cfg.extra).items()},
    }


def audit_layers_summary(src: SourceMap) -> list[str]:
    """Human-friendly summary of layer counts in fixed order."""
    counts = summarize_origins(src)
    order = ["default", "home", "project", "env", "overrides"]
    return [f"{name:9s}: {counts.get(name, 0)} fields" for name in order]


def doctor() -> list[str]:
    """Quick environment/config check with actionable messages."""
    msgs: list[str] = []
    advisories: list[str] = []
    cfg, src = resolve_config(explain=True)
    if cfg.use_real_api and not cfg.api_key:
        msgs.append("use_real_api=True but api_key is missing.")
    if cfg.ttl_seconds < 0:
        msgs.append("ttl_seconds < 0 (must be >= 0).")
    if cfg.provider == "google" and not cfg.model.lower().startswith(
        ("gemini-", "google-")
    ):
        msgs.append("Unknown model; provider defaulted to 'google'.")
    # Gentle, non-failing advisory for defaulted tier
    fo = src.get("tier")
    if fo and fo.origin is Origin.DEFAULT:
        tier_label = cfg.tier.name if hasattr(cfg.tier, "name") else str(cfg.tier)
        advisories.append(
            f"Advisory: 'tier' not specified; using default {tier_label}. "
            + field_spec_hint("tier")
        )
    if not msgs:
        msgs.append("No issues detected.")
    return msgs + advisories


# --- Minimal CLI entrypoint (optional) ---


def main() -> int:  # pragma: no cover - thin utility  # noqa: D103
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser("pollux-config")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    sub.add_parser("audit")
    sub.add_parser("doctor")
    sub.add_parser("env")
    args = parser.parse_args()

    if args.cmd == "show":
        cfg = resolve_config()
        sys.stdout.write(json.dumps(to_redacted_dict(cfg), indent=2) + "\n")
    elif args.cmd == "audit":
        cfg, src = resolve_config(explain=True)
        sys.stdout.write(audit_text(cfg, src) + "\n")
        for line in audit_layers_summary(src):
            sys.stdout.write(line + "\n")
    elif args.cmd == "doctor":
        for m in doctor():
            sys.stdout.write(m + "\n")
    elif args.cmd == "env":
        env_vars = check_environment()
        for k, v in sorted(env_vars.items()):
            sys.stdout.write(f"{k}={v}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
