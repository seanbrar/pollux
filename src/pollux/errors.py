"""Exception hierarchy for Pollux."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


class PolluxError(Exception):
    """Base exception for all Pollux errors."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class ConfigurationError(PolluxError):
    """Configuration validation or resolution failed."""


class SourceError(PolluxError):
    """Source validation or loading failed."""


class PlanningError(PolluxError):
    """Execution planning failed."""


class InternalError(PolluxError):
    """A Pollux internal error (bug) or invariant violation."""


class APIError(PolluxError):
    """API call failed.

    Providers attach retry metadata so core execution can perform bounded
    retries without brittle substring matching.
    """

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        retryable: bool | None = None,
        status_code: int | None = None,
        retry_after_s: float | None = None,
        provider: str | None = None,
        phase: str | None = None,
        call_idx: int | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_s = retry_after_s
        self.provider = provider
        self.phase = phase
        self.call_idx = call_idx


class CacheError(APIError):
    """Cache operation failed."""


class RateLimitError(APIError):
    """Rate limit exceeded (HTTP 429)."""


def _walk_exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield *exc* and its ``__cause__``/``__context__`` chain, with cycle protection."""
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        cur = stack.pop()
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        yield cur

        cause = cur.__cause__
        if isinstance(cause, BaseException):
            stack.append(cause)
        context = cur.__context__
        if isinstance(context, BaseException):
            stack.append(context)
