"""Exception hierarchy for Pollux."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
        error_category: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_s = retry_after_s
        self.provider = provider
        self.phase = phase
        self.call_idx = call_idx
        self.error_category = error_category


class ContextOverflowError(APIError):
    """Provider rejected a request because it exceeded the context window."""

    def __init__(
        self,
        message: str,
        *,
        n_tokens: int | None = None,
        n_ctx: int | None = None,
        hint: str | None = None,
        retryable: bool | None = None,
        status_code: int | None = None,
        retry_after_s: float | None = None,
        provider: str | None = None,
        phase: str | None = None,
        call_idx: int | None = None,
    ) -> None:
        super().__init__(
            message,
            hint=hint,
            retryable=retryable,
            status_code=status_code,
            retry_after_s=retry_after_s,
            provider=provider,
            phase=phase,
            call_idx=call_idx,
            error_category="context_overflow",
        )
        self.n_tokens = n_tokens
        self.n_ctx = n_ctx


class ToolCallParseError(APIError):
    """A model-emitted tool call could not be parsed for dispatch."""

    def __init__(
        self,
        message: str,
        *,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        arguments_text: str | None = None,
        hint: str | None = None,
        provider: str | None = None,
        phase: str | None = None,
    ) -> None:
        super().__init__(
            message,
            hint=hint,
            retryable=False,
            provider=provider,
            phase=phase,
            error_category="tool_call_parse",
        )
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        self.arguments_text = arguments_text


class CacheError(APIError):
    """Cache operation failed."""


class RateLimitError(APIError):
    """Rate limit exceeded (HTTP 429)."""


class DeferredNotReadyError(PolluxError):
    """Deferred job is not yet in a terminal state."""

    def __init__(self, snapshot: Any) -> None:
        super().__init__(
            "Deferred job is not ready to collect",
            hint="Inspect the attached snapshot and retry after the job reaches a terminal state.",
        )
        self.snapshot = snapshot


def walk_exception_chain(exc: BaseException) -> Iterator[BaseException]:
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
