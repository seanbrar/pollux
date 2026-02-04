"""Exception hierarchy for Pollux."""

from __future__ import annotations


class PolluxError(Exception):
    """Base exception for all Pollux errors."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        """Initialize PolluxError."""
        super().__init__(message)
        self.hint = hint


class ConfigurationError(PolluxError):
    """Configuration validation or resolution failed."""


class SourceError(PolluxError):
    """Source validation or loading failed."""


class PlanningError(PolluxError):
    """Execution planning failed."""


class APIError(PolluxError):
    """API call failed."""


class CacheError(PolluxError):
    """Cache operation failed."""


class RateLimitError(PolluxError):
    """Rate limit exceeded."""
