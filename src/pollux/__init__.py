"""Gemini Batch: Efficient, scenario-first batch interactions with Gemini APIs."""

from __future__ import annotations

import importlib.metadata
import logging

from pollux.core.exceptions import GeminiBatchError
from pollux.executor import GeminiExecutor, create_executor
from pollux.frontdoor import (
    run_batch,
    run_multi,
    run_parallel,
    run_rag,
    run_simple,
    run_synthesis,
)

# Curated public namespaces for clarity
from . import exceptions as exceptions  # Re-exported public exceptions
from . import research as research  # Progressive disclosure: research helpers
from . import types as types  # Re-exported public types

# Version handling
try:
    __version__ = importlib.metadata.version("pollux")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - dev mode
    __version__ = "development"

# Set up a null handler for the library's root logger to be polite to apps
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [  # noqa: RUF022
    # Primary entry points
    "GeminiExecutor",
    "create_executor",
    "run_simple",
    "run_batch",
    "run_rag",
    "run_multi",
    "run_synthesis",
    "run_parallel",
    # Root exception and curated namespaces
    "GeminiBatchError",
    "types",
    "exceptions",
    "research",
]
