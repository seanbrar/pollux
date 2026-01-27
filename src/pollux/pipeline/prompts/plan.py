"""Declarative plan for prompt assembly.

This module defines a minimal, immutable ``AssemblyPlan`` data object that
captures precedence decisions derived from configuration and context.
Transforms interpret the plan to produce the final ``PromptBundle``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .config_types import SourcesPolicy


@dataclass(frozen=True, slots=True)
class AssemblyPlan:
    """Declarative plan driving prompt assembly.

    - ``system_base`` chooses the base system source (inline, file, or none).
    - ``user_strategy`` selects between inline prompts or reading a file.
    - ``sources_policy`` and ``sources_block`` drive source-aware guidance.
    - ``sources_action`` is a precomputed decision (none/append/replace).
    - ``prefix``/``suffix`` are applied only to inline user prompts.
    """

    system_base: Literal["inline", "file", None]
    user_strategy: Literal["inline", "from_file"]
    sources_policy: SourcesPolicy
    sources_block: str | None
    sources_action: Literal["none", "append", "replace"]
    prefix: str
    suffix: str
