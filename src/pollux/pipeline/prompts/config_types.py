"""Typed configuration for prompt assembly.

This module defines the typed view of ``prompts.*`` configuration and the
``SourcesPolicy`` used to control source-aware guidance.

Public keys under ``prompts.`` supported by the assembler:
- system: str | None
- system_file: str | Path | None
- prefix: str (default: "")
- suffix: str (default: "")
- user_file: str | Path | None
- encoding: str (default: "utf-8")
- strip: bool (default: True)
- max_bytes: int (default: 128_000)
- sources_policy: one of {"never","replace","append_or_replace"}
- sources_block: str | None
- builder: str | None (``module:function``)

Note: the legacy key ``prompts.apply_if_sources`` has been removed. Use
``prompts.sources_policy='append_or_replace'`` to mirror the old behavior
where a sources block would augment or replace the base system.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

from pollux.core.exceptions import ConfigurationError

SourcesPolicy = Literal["never", "replace", "append_or_replace"]


@dataclass(frozen=True, slots=True)
class PromptsConfig:
    """Typed view of ``prompts.*`` configuration with validation."""

    # Inline and file-based system guidance
    system: str | None = None
    system_file: str | Path | None = None

    # Dynamic source-aware guidance
    # WARNING: When set to "replace" and sources are present, any configured
    # system prompt (inline or file) will be replaced by `sources_block`.
    # Use "append_or_replace" to append when a base system exists; otherwise replace.
    sources_policy: SourcesPolicy = "never"
    sources_block: str | None = None

    # User prompt transforms
    prefix: str = ""
    suffix: str = ""
    user_file: str | Path | None = None

    # File reading options
    encoding: str = "utf-8"
    strip: bool = True
    max_bytes: int = 128_000

    # Advanced hook (module:function)
    builder: str | None = None

    # Diagnostics: unknown keys under prompts.*
    unknown_keys: tuple[str, ...] = ()


def extract_prompts_config(extra: Mapping[str, Any]) -> PromptsConfig:
    """Extract and validate ``prompts.*`` keys from a config ``extra`` mapping.

    This is a pure, local extractor that returns a typed ``PromptsConfig``.
    It performs lightweight validation and preserves unknown keys for hints.
    """
    allowed = {
        "system",
        "system_file",
        "sources_block",
        "sources_policy",
        "prefix",
        "suffix",
        "user_file",
        "encoding",
        "strip",
        "max_bytes",
        "builder",
    }

    known: dict[str, Any] = {}
    unknown: list[str] = []
    for key, value in extra.items():
        if not key.startswith("prompts."):
            continue
        k = key[8:]
        if k == "apply_if_sources":
            raise ConfigurationError(
                "prompts.apply_if_sources has been removed. Set prompts.sources_policy to 'append_or_replace' to mirror the old behavior, or choose one of {'never','replace','append_or_replace'}."
            )
        if k in allowed:
            known[k] = value
        else:
            unknown.append(k)

    # Coerce simple types with clear errors; keep behavior from prior extractor
    def as_opt_str(name: str) -> str | None:
        v = known.get(name)
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s != "" else None
        raise ConfigurationError(f"prompts.{name} must be a string if provided")

    def as_opt_pathlike(name: str) -> str | Path | None:
        v = known.get(name)
        if v is None:
            return None
        if isinstance(v, str | Path):
            return v
        raise ConfigurationError(f"prompts.{name} must be a str or Path")

    def as_bool(name: str, *, default: bool = False) -> bool:
        v = known.get(name, default)
        if isinstance(v, bool):
            return v
        raise ConfigurationError(f"prompts.{name} must be a boolean")

    def as_str(name: str, default: str = "") -> str:
        v = known.get(name, default)
        if isinstance(v, str):
            return v
        raise ConfigurationError(f"prompts.{name} must be a string")

    def as_int(name: str, default: int) -> int:
        v = known.get(name, default)
        if isinstance(v, bool):  # guard: bool is int subclass
            raise ConfigurationError(f"prompts.{name} must be an int, not bool")
        if isinstance(v, int):
            return v
        raise ConfigurationError(f"prompts.{name} must be an int")

    explicit_policy = known.get("sources_policy")
    sources_policy: SourcesPolicy
    if explicit_policy is None:
        sources_policy = "never"
    else:
        if explicit_policy not in ("never", "replace", "append_or_replace"):
            raise ConfigurationError(
                "prompts.sources_policy must be one of 'never','replace','append_or_replace'"
            )
        sources_policy = explicit_policy

    cfg = PromptsConfig(
        system=as_opt_str("system"),
        system_file=as_opt_pathlike("system_file"),
        sources_policy=sources_policy,
        sources_block=as_opt_str("sources_block"),
        prefix=as_str("prefix", ""),
        suffix=as_str("suffix", ""),
        user_file=as_opt_pathlike("user_file"),
        encoding=as_str("encoding", "utf-8"),
        strip=as_bool("strip", default=True),
        max_bytes=as_int("max_bytes", 128_000),
        builder=as_opt_str("builder"),
        unknown_keys=tuple(unknown),
    )

    if cfg.max_bytes <= 0:
        raise ConfigurationError("prompts.max_bytes must be > 0")

    return cfg
