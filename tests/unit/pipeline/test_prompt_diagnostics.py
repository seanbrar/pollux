"""Unit tests for prompt assembly diagnostics.

Focus: Ensure diagnostics reflect key decisions and warn on sharp edges.
"""

import pytest

from pollux.config import resolve_config
from pollux.core.types import InitialCommand, ResolvedCommand, Source
from pollux.pipeline.prompts import explain_prompt_assembly

pytestmark = pytest.mark.unit


def test_explain_prompt_assembly_warns_on_replace_when_sources_and_system() -> None:
    cfg = resolve_config(
        overrides={
            "prompts.system": "Base system",  # will be replaced
            "prompts.sources_policy": "replace",
            "prompts.sources_block": "Use the provided sources strictly.",
        }
    )
    initial = InitialCommand(
        sources=(),
        prompts=("Question?",),
        config=cfg,
    )
    # Presence of any source should trigger sources-aware path
    command = ResolvedCommand(
        initial=initial,
        resolved_sources=(Source.from_text("content", identifier="s1"),),
    )

    diag = explain_prompt_assembly(command)

    # Key flags present
    assert "- sources_policy: replace" in diag
    assert "- sources_block_applied: yes" in diag
    # Provenance should reflect replacement source
    assert "provenance.system_from: sources_block" in diag
    # Warning for the replace sharp edge
    assert "WARNING: prompts.system is set, but sources_policy is 'replace'" in diag


def test_explain_prompt_assembly_includes_counts() -> None:
    cfg = resolve_config(
        overrides={
            "prompts.prefix": "P: ",
            "prompts.suffix": " S",
        }
    )
    initial = InitialCommand(
        sources=(),
        prompts=("a", "b"),
        config=cfg,
    )
    command = ResolvedCommand(initial=initial, resolved_sources=())

    diag = explain_prompt_assembly(command)

    assert "- user_prompt_count: 2" in diag
    # Even without a system prompt, preview line should exist (empty allowed)
    assert "- effective_system_preview:" in diag
