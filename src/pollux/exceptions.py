"""Public exceptions surface for end-users.

Re-exports core exception types under a dedicated, discoverable module.
"""

from __future__ import annotations

from pollux.core.exceptions import (
    ConfigurationError,
    FileError,
    PipelineError,
    PolluxError,
    SourceError,
    UnsupportedContentError,
    ValidationError,
)

__all__ = [
    "ConfigurationError",
    "FileError",
    "PipelineError",
    "PolluxError",
    "SourceError",
    "UnsupportedContentError",
    "ValidationError",
]
