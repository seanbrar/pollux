"""Compatibility shim for core types.

This module re-exports all types from the new modular structure to maintain
backward compatibility. All types have been moved to more focused modules.
"""

from __future__ import annotations

import typing

# API parts & config
from .api_parts import (
    APIPart,
    FileInlinePart,
    FilePlaceholder,
    FileRefPart,
    GenerationConfigDict,
    HistoryPart,
    TextPart,
)

# Plan & commands
from .api_plan import APICall, ExecutionPlan, UploadTask
from .commands import FinalizedCommand, InitialCommand, PlannedCommand, ResolvedCommand
from .prompts_bundle import PromptBundle
from .rate_limits import RateConstraint
from .result_envelope import (
    ResultEnvelope,
    explain_invalid_result_envelope,
    is_result_envelope,
)

# Results
from .result_primitives import Failure, Result, Success

# Sources
from .sources import Source

# Tokens & rate limits
from .tokens import TokenEstimate

# Conversation & prompts
from .turn import Turn

# Ensure external dependency visibility for tests without runtime import
if typing.TYPE_CHECKING:  # pragma: no cover - import for dependency visibility only
    from google.genai import types as genai_types  # noqa: F401

__all__ = [
    "APICall",
    "APIPart",
    "ExecutionPlan",
    "Failure",
    "FileInlinePart",
    "FilePlaceholder",
    "FileRefPart",
    "FinalizedCommand",
    "GenerationConfigDict",
    "HistoryPart",
    "InitialCommand",
    "PlannedCommand",
    "PromptBundle",
    "RateConstraint",
    "ResolvedCommand",
    "Result",
    "ResultEnvelope",
    "Source",
    "Success",
    "TextPart",
    "TokenEstimate",
    "Turn",
    "UploadTask",
    "explain_invalid_result_envelope",
    "is_result_envelope",
]

# Hide the __future__ feature binding from the public surface if present
try:  # pragma: no cover - environment specific  # noqa: SIM105
    del annotations
except NameError:  # pragma: no cover - defensive
    pass
