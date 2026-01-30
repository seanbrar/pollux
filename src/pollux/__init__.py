"""Pollux: Efficient, scenario-first batch interactions with Gemini APIs."""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
from typing import TYPE_CHECKING

from pollux.core.exceptions import PolluxError

if TYPE_CHECKING:
    import pollux.exceptions as exceptions
    from pollux.executor import Executor, create_executor
    from pollux.frontdoor import (
        run_batch,
        run_multi,
        run_parallel,
        run_rag,
        run_simple,
        run_synthesis,
    )
    import pollux.research as research
    import pollux.types as types

# Version handling
try:
    __version__ = importlib.metadata.version("pollux")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - dev mode
    __version__ = "development"

# Set up a null handler for the library's root logger to be polite to apps
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [  # noqa: RUF022
    # Primary entry points
    "Executor",
    "create_executor",
    "run_simple",
    "run_batch",
    "run_rag",
    "run_multi",
    "run_synthesis",
    "run_parallel",
    # Root exception and curated namespaces
    "PolluxError",
    "types",
    "exceptions",
    "research",
]

_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "Executor": ("pollux.executor", "Executor"),
    "create_executor": ("pollux.executor", "create_executor"),
    "run_simple": ("pollux.frontdoor", "run_simple"),
    "run_batch": ("pollux.frontdoor", "run_batch"),
    "run_rag": ("pollux.frontdoor", "run_rag"),
    "run_multi": ("pollux.frontdoor", "run_multi"),
    "run_synthesis": ("pollux.frontdoor", "run_synthesis"),
    "run_parallel": ("pollux.frontdoor", "run_parallel"),
}

_LAZY_MODULES: dict[str, str] = {
    "exceptions": "pollux.exceptions",
    "research": "pollux.research",
    "types": "pollux.types",
}


def __getattr__(name: str) -> object:
    if name in _LAZY_MODULES:
        module = importlib.import_module(_LAZY_MODULES[name])
        globals()[name] = module
        return module
    if name in _LAZY_ATTRS:
        module_name, attr_name = _LAZY_ATTRS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_LAZY_ATTRS) + list(_LAZY_MODULES))
