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

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        retryable: bool | None = None,
        status_code: int | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        """Initialize APIError.

        Providers may optionally attach retry metadata so core execution can
        perform bounded retries without brittle substring matching.
        """
        super().__init__(message, hint=hint)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_s = retry_after_s


class CacheError(PolluxError):
    """Cache operation failed."""


class RateLimitError(PolluxError):
    """Rate limit exceeded."""
