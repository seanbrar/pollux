"""Prompt assembly system for the pipeline.

This package provides the prompt assembler functionality for composing prompts
from configuration, files, and advanced builder hooks. The assembled results
are returned as `PromptBundle` from `pollux.core.types`.
"""

from .assembler import assemble_prompts
from .config_types import PromptsConfig, SourcesPolicy
from .diagnostics import explain_prompt_assembly

__all__ = [
    "PromptsConfig",
    "SourcesPolicy",
    "assemble_prompts",
    "explain_prompt_assembly",
]
