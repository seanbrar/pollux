"""Core exceptions for the Gemini Batch Pipeline.

This module consolidates all custom exceptions for the library, providing a clear
hierarchy for error handling. The pipeline-specific exceptions allow for more
granular error catching and reporting.
"""


class GeminiBatchError(Exception):
    """Base exception for all library-specific errors."""


class APIError(GeminiBatchError):
    """Raised for errors originating from the Gemini API."""


# --- Command Pipeline Exceptions ---
# These new exceptions map directly to stages of the pipeline, allowing
# the executor or user to understand exactly where a failure occurred.


class PipelineError(GeminiBatchError):
    """Raised when a step in the execution pipeline fails."""

    def __init__(self, message: str, handler_name: str, underlying_error: Exception):
        """Initialize a PipelineError."""
        self.handler_name = handler_name
        self.underlying_error = underlying_error
        super().__init__(f"Error in handler '{handler_name}': {message}")


class ConfigurationError(GeminiBatchError):
    """Raised for invalid or missing configuration."""


class SourceError(GeminiBatchError):
    """Raised for errors related to input source processing (e.g., file not found)."""


# --- Legacy Exceptions (to be phased out or mapped) ---


class MissingKeyError(GeminiBatchError):
    """Raised when required API key or configuration key is missing."""


class FileError(GeminiBatchError):
    """Raised when file operations fail."""


class ValidationError(GeminiBatchError):
    """Raised when input validation fails."""


class UnsupportedContentError(GeminiBatchError):
    """Raised when content type is not supported."""


class InvariantViolationError(GeminiBatchError):
    """Raised when an internal pipeline invariant is violated.

    Used to signal impossible states that indicate a bug or mis-composed pipeline,
    e.g., when the final stage does not produce a ResultEnvelope.
    """

    def __init__(self, message: str, stage_name: str | None = None):
        """Create an invariant violation error.

        Args:
            message: Human-readable description of the violated invariant.
            stage_name: Optional pipeline stage name where the issue was detected.
        """
        self.stage_name = stage_name
        super().__init__(message if stage_name is None else f"[{stage_name}] {message}")
