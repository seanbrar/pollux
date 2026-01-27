"""Diagnostics for prompt assembly behavior.

Provides helpers to preview assembled prompts and surface sharp edges,
notably interactions between `prompts.system` and `prompts.sources_policy`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .assembler import assemble_prompts
from .config_types import PromptsConfig, extract_prompts_config

if TYPE_CHECKING:
    from pollux.core.types import PromptBundle, ResolvedCommand


def explain_prompt_assembly(command: ResolvedCommand) -> str:
    """Return a human-readable explanation of prompt assembly decisions.

    Includes the effective system instruction, user prompts (after transforms),
    whether a sources-aware block was applied, and the active `sources_policy`.
    Emits a WARNING when a system prompt would be replaced by `sources_block`.
    """
    cfg: PromptsConfig = extract_prompts_config(command.initial.config.extra)
    bundle: PromptBundle = assemble_prompts(command)

    has_sources = bool(command.resolved_sources)
    policy = cfg.sources_policy
    applied_block = bool(cfg.sources_block and has_sources)

    lines: list[str] = []
    lines.append("Prompt Assembly Diagnostics")
    lines.append("- sources_present: %s" % ("yes" if has_sources else "no"))
    lines.append(f"- sources_policy: {policy}")
    lines.append(
        f"- sources_block_configured: {'yes' if bool(cfg.sources_block) else 'no'}"
    )
    lines.append(f"- sources_block_applied: {'yes' if applied_block else 'no'}")
    lines.append(
        f"- system_from_config: {'yes' if bool(cfg.system or cfg.system_file) else 'no'}"
    )
    lines.append(f"- effective_system_len: {len(bundle.system or '')}")
    lines.append(f"- user_prompt_count: {len(bundle.user)}")

    # Provenance highlights to make decisions explicit without leaking content
    prov = bundle.provenance
    system_from = prov.get("system_from")
    if system_from:
        lines.append(f"- provenance.system_from: {system_from}")
    sources_decision = prov.get("sources_decision")
    if sources_decision:
        lines.append(f"- provenance.sources_decision: {sources_decision}")
    if prov.get("sources_block_applied"):
        lines.append("- provenance.sources_block_applied: yes")
    if prov.get("sources_block_skipped"):
        lines.append("- provenance.sources_block_skipped: yes")
    if "sources_block_len" in prov:
        lines.append(f"- provenance.sources_block_len: {prov['sources_block_len']}")
    if "unknown_prompt_keys" in prov:
        lines.append(
            f"- provenance.unknown_prompt_keys: {', '.join(prov['unknown_prompt_keys'])}"
        )

    # Sharp edge warning
    if (
        has_sources
        and policy == "replace"
        and (cfg.system or cfg.system_file)
        and cfg.sources_block
    ):
        lines.append(
            "WARNING: prompts.system is set, but sources_policy is 'replace' and sources are present. "
            "The system prompt will be replaced by prompts.sources_block."
        )

    # Show a preview (truncated lengths only; not content) to avoid leaking data
    def _preview(s: str, limit: int = 80) -> str:
        s = s.replace("\n", " ")
        return (s[: limit - 3] + "...") if len(s) > limit else s

    lines.append(
        "- effective_system_preview: {}".format(_preview(bundle.system or "", 120))
    )
    for idx, up in enumerate(bundle.user, start=1):
        lines.append(f"- user[{idx}]: {_preview(up)}")

    return "\n".join(lines)
