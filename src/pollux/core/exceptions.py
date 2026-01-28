"""Core exceptions for Pollux.

This module consolidates all custom exceptions for the library, providing a clear
hierarchy for error handling. The pipeline-specific exceptions allow for more
granular error catching and reporting.
"""


class PolluxError(Exception):
    """Base exception for all library-specific errors."""

    def __init__(self, message: str | None, hint: str | None = None):
        """Initialize with an optional actionable hint."""
        self.hint = hint
        # Store just the message in the base Exception for clean programmatic access
        msg_str = str(message) if message is not None else "None"
        super().__init__(msg_str)

    def __str__(self) -> str:
        """Return the full error message including the hint."""
        msg = super().__str__()
        return f"{msg}. {self.hint}" if self.hint else msg


# --- Actionable Hints ---

HINTS = {
    "missing_api_key": (
        "Set GEMINI_API_KEY environment variable or provide api_key in configuration. "
        "Run pollux.config.doctor() to diagnose."
    ),
    "invalid_source": (
        "Use Source.from_text() for text content or Source.from_file() for files. "
        "Strings are not accepted directly."
    ),
    "pdf_not_installed": (
        "PDF support requires the 'pdf' extra. Install with: pip install pollux[pdf]"
    ),
    "image_not_installed": (
        "Image support requires the 'images' extra. Install with: pip install pollux[images]"
    ),
    "magic_not_installed": (
        "MIME detection requires the 'magic' extra. Install with: pip install pollux[magic]"
    ),
    "rate_limited": "Rate limit exceeded. Wait and retry, or upgrade your API tier.",
}

_HTTP_ERROR_HINTS = {
    401: "Verify GEMINI_API_KEY is valid.",
    403: "Check API key permissions or project status.",
    404: "Model not found or API endpoint invalid.",
    429: "Rate limit exceeded; wait and retry.",
    500: "Gemini API internal error; retry later.",
    503: "Service unavailable; the model might be overloaded.",
}


def get_http_error_hint(status_code: int) -> str | None:
    """Return an actionable hint for a given HTTP status code."""
    return _HTTP_ERROR_HINTS.get(status_code)


class APIError(PolluxError):
    """Raised for errors originating from the Gemini API."""


# --- Command Pipeline Exceptions ---
# These new exceptions map directly to stages of the pipeline, allowing
# the executor or user to understand exactly where a failure occurred.


class PipelineError(PolluxError):
    """Raised when a step in the execution pipeline fails."""

    def __init__(
        self,
        message: str,
        handler_name: str,
        underlying_error: Exception,
        hint: str | None = None,
    ):
        """Initialize a PipelineError."""
        self.handler_name = handler_name
        self.underlying_error = underlying_error
        super().__init__(f"Error in handler '{handler_name}': {message}", hint=hint)


class ConfigurationError(PolluxError):
    """Raised for invalid or missing configuration."""


class SourceError(PolluxError):
    """Raised for errors related to input source processing (e.g., file not found)."""


# --- Legacy Exceptions (to be phased out or mapped) ---


class MissingKeyError(PolluxError):
    """Raised when required API key or configuration key is missing."""


class FileError(PolluxError):
    """Raised when file operations fail."""


class ValidationError(PolluxError):
    """Raised when input validation fails."""


class UnsupportedContentError(PolluxError):
    """Raised when content type is not supported."""


class InvariantViolationError(PolluxError):
    """Raised when an internal pipeline invariant is violated.

    Used to signal impossible states that indicate a bug or mis-composed pipeline,
    e.g., when the final stage does not produce a ResultEnvelope.
    """

    def __init__(
        self, message: str, stage_name: str | None = None, hint: str | None = None
    ):
        """Create an invariant violation error.

        Args:
            message: Human-readable description of the violated invariant.
            stage_name: Optional pipeline stage name where the issue was detected.
            hint: Optional actionable hint for resolution.
        """
        self.stage_name = stage_name
        msg = message if stage_name is None else f"[{stage_name}] {message}"
        super().__init__(msg, hint=hint)
