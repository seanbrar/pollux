"""Default prompt assembler implementation.

Overview
--------
Pure function that assembles a ``PromptBundle`` from a ``ResolvedCommand``.
It applies explicit, predictable precedence rules to combine inline values,
files, and optional source-aware guidance. Advanced use-cases can provide a
builder hook to replace the default logic entirely.

Sharp edge: source-aware guidance
--------------------------------
Set ``prompts.sources_policy`` to one of:
- ``never``: ignore ``sources_block`` entirely.
- ``replace``: when sources exist, the system becomes ``sources_block``.
- ``append_or_replace``: append if a base system exists; otherwise, replace.

Inline or file-based ``prompts.system`` is never silently dropped without
sources. Provenance is recorded in ``PromptBundle.provenance``
(``sources_policy``, ``sources_block_applied``, ``sources_block_skipped``).
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Literal, cast

from pollux.core.exceptions import ConfigurationError
from pollux.core.types import PromptBundle, ResolvedCommand

from .config_types import PromptsConfig as _PromptsConfig
from .config_types import extract_prompts_config
from .plan import AssemblyPlan


def assemble_prompts(
    command: ResolvedCommand,
) -> PromptBundle:
    """Assemble prompts from configuration into an immutable PromptBundle.

    This is a pure function that composes prompts according to the documented
    precedence rules and invariants. It supports:
    - Inline configuration (system, prefix, suffix)
    - File inputs (system_file, user_file)
    - Source-aware guidance (sources_policy, sources_block)
    - Advanced builder hooks (builder)

    Args:
        command: ResolvedCommand with initial prompts and configuration.

    Returns:
        PromptBundle with assembled prompts and provenance mapping.

    Raises:
        ConfigurationError: If file reading fails, builder hook errors,
            or configuration is invalid.
    """
    config = command.initial.config
    initial_prompts = command.initial.prompts
    has_sources = bool(command.resolved_sources)

    # Extract and validate prompts configuration from extra fields
    prompts_cfg = extract_prompts_config(config.extra)

    # Check for advanced builder hook first (explicit escape hatch)
    if prompts_cfg.builder is not None:
        return _call_builder_hook(prompts_cfg.builder, command, prompts_cfg)

    # Plan-driven micro-transforms
    plan = plan_for(
        prompts_cfg,
        has_sources=has_sources,
        has_inline_prompts=bool(initial_prompts),
    )

    system_1, provenance_1 = t_resolve_system(plan, prompts_cfg)
    system_2, provenance_2 = t_apply_sources_policy(plan, system_1)
    user_prompts, provenance_3 = t_resolve_user_prompts(
        plan, prompts_cfg, initial_prompts
    )

    provenance = {
        **provenance_1,
        **provenance_2,
        **provenance_3,
        "has_sources": has_sources,
        "sources_policy": plan.sources_policy,
        "sources_decision": plan.sources_action,
    }
    # Flag to make replacement explicit in diagnostics/telemetry consumers
    provenance["system_replaced_by_sources"] = plan.sources_action == "replace"
    if plan.sources_block is not None:
        provenance["sources_block_len"] = len(plan.sources_block)
    if prompts_cfg.unknown_keys:
        provenance["unknown_prompt_keys"] = prompts_cfg.unknown_keys
    if system_2 is not None:
        provenance["system_len"] = len(system_2)
    provenance["user_total_len"] = sum(len(p) for p in user_prompts)

    return PromptBundle(user=user_prompts, system=system_2, provenance=provenance)


# --- Internal helpers ---


def plan_for(
    cfg: _PromptsConfig,
    *,
    has_sources: bool,
    has_inline_prompts: bool,
) -> AssemblyPlan:
    """Build a declarative plan from validated config and context."""
    system_base: Literal["inline", "file"] | None
    if cfg.system is not None:
        system_base = "inline"
    elif cfg.system_file is not None:
        system_base = "file"
    else:
        system_base = None

    user_strategy: Literal["inline", "from_file"] = (
        "inline" if has_inline_prompts else "from_file"
    )

    # Precompute sources action to remove branching later
    sources_block = cfg.sources_block
    if not (has_sources and sources_block and cfg.sources_policy != "never"):
        sources_action: Literal["none", "append", "replace"] = "none"
    elif cfg.sources_policy == "replace":
        sources_action = "replace"
    else:  # append_or_replace
        sources_action = "append" if system_base is not None else "replace"

    return AssemblyPlan(
        system_base=system_base,
        user_strategy=user_strategy,
        sources_policy=cfg.sources_policy,
        sources_block=cfg.sources_block,
        sources_action=sources_action,
        prefix=cfg.prefix,
        suffix=cfg.suffix,
    )


def t_resolve_system(
    plan: AssemblyPlan, cfg: _PromptsConfig
) -> tuple[str | None, dict[str, Any]]:
    """Resolve the base system according to the plan. Isolated file I/O."""
    provenance: dict[str, Any] = {}

    if plan.system_base == "inline":
        if cfg.system_file is not None:
            provenance["system_file_ignored"] = True
        provenance["system_from"] = "inline"
        return cfg.system, provenance

    if plan.system_base == "file":
        path = cast("str | Path", cfg.system_file)
        system = _read_prompt_file(path, cfg)
        provenance["system_from"] = "system_file"
        provenance["system_file"] = str(path)
        return system, provenance

    return None, provenance


def t_apply_sources_policy(
    plan: AssemblyPlan, base_system: str | None
) -> tuple[str | None, dict[str, Any]]:
    """Apply source-aware guidance to the base system deterministically."""
    hints: dict[str, Any] = {"sources_policy": plan.sources_policy}
    sources_block = plan.sources_block

    if plan.sources_action == "none" or not sources_block:
        if sources_block:
            hints["sources_block_skipped"] = True
        return base_system, hints

    if plan.sources_action == "replace":
        hints["system_from"] = "sources_block"
        hints["sources_block_applied"] = True
        return sources_block, hints

    # append
    if base_system is not None:
        hints["sources_block_applied"] = True
        return f"{base_system}\n\n{sources_block}".strip(), hints

    return base_system, hints


def t_resolve_user_prompts(
    plan: AssemblyPlan, cfg: _PromptsConfig, initial_prompts: tuple[str, ...]
) -> tuple[tuple[str, ...], dict[str, Any]]:
    """Derive user prompts either from inline inputs or a file."""
    hints: dict[str, Any] = {}

    if plan.user_strategy == "inline":
        prefix, suffix = plan.prefix, plan.suffix
        if prefix:
            hints["prefix_len"] = len(prefix)
        if suffix:
            hints["suffix_len"] = len(suffix)
        # Symmetry with system_file_ignored: surface when user_file is ignored
        if cfg.user_file is not None:
            hints["user_file_ignored"] = True
        users = tuple(f"{prefix}{p}{suffix}".strip() for p in initial_prompts)
        hints["user_from"] = "initial"
        return users, hints

    # from_file
    if cfg.user_file is None:
        raise ConfigurationError(
            "No prompts provided. Either pass prompts to InitialCommand or set prompts.user_file"
        )
    content = _read_prompt_file(cfg.user_file, cfg)
    hints["user_from"] = "user_file"
    hints["user_file"] = str(cfg.user_file)
    return (content,), hints


def _read_prompt_file(file_path: str | Path, prompts_config: _PromptsConfig) -> str:
    """Read a prompt file with size guard and clear errors.

    Reads bytes first to enforce ``max_bytes`` precisely, then decodes using the
    configured encoding. Trailing newlines can be stripped for ergonomics.
    """
    path = Path(file_path)

    # Extract configuration
    encoding = prompts_config.encoding
    strip_newlines = prompts_config.strip
    max_bytes = prompts_config.max_bytes

    # Read bytes, then decode to ensure byte-accurate size checks
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise ConfigurationError(
            f"Prompt file '{path}' not found. Check the file path or create the file."
        ) from None
    except PermissionError:
        raise ConfigurationError(
            f"Permission denied reading '{path}'. Check file permissions."
        ) from None
    except Exception as e:
        raise ConfigurationError(f"Failed to read prompt file '{path}': {e}") from e

    if len(raw) > max_bytes:
        raise ConfigurationError(
            f"Prompt file '{path}' is too large ({len(raw):,} bytes). "
            f"Reduce file size or increase prompts.max_bytes (current: {max_bytes:,})."
        )

    try:
        content = raw.decode(encoding)
    except UnicodeDecodeError:
        raise ConfigurationError(
            f"Prompt file '{path}' encoding issue. "
            f"Try setting prompts.encoding to a different value (current: '{encoding}')."
        ) from None

    if strip_newlines:
        content = content.rstrip("\n\r")

    return content


def _call_builder_hook(
    builder_path: str, command: ResolvedCommand, cfg: _PromptsConfig
) -> PromptBundle:
    """Call an advanced builder hook function with minimal intervention."""
    try:
        # Parse dotted path: "pkg.mod:fn"
        if ":" not in builder_path:
            raise ConfigurationError(
                f"Invalid builder path '{builder_path}': use format 'module:function'"
            )

        module_path, function_name = builder_path.split(":", 1)
        module = importlib.import_module(module_path)
        builder_fn = getattr(module, function_name)

        # Prefer new-style signature (command, cfg) with fallback to (command)
        try:
            result = builder_fn(command, cfg)
        except TypeError:
            result = builder_fn(command)

        # Quick type check - if it's wrong, the error will be clear
        if not isinstance(result, PromptBundle):
            raise ConfigurationError(
                f"Builder '{builder_path}' returned {type(result).__name__}, expected PromptBundle"
            )

        return result

    except Exception as e:
        raise ConfigurationError(f"Builder '{builder_path}' failed: {e}") from e
