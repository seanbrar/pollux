"""Provider-specific upload helpers (optional extension).

Goal: make file handling simple and reliable for apps that need to pre-upload
local files to a provider and wait until they are usable by APIs that require
an "ACTIVE" file state.

Design:
- Minimal, explicit API with safe defaults and clear errors
- Optional dependency on provider SDKs (imported at runtime only)
- Simple polling with timeout and backoff; callers control timing knobs
- Uses the project's configuration resolution to source credentials when present

Currently supported provider: "google" via the `google-genai` SDK.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import time
from typing import Any, Final, Protocol, runtime_checkable

log = logging.getLogger(__name__)

__all__ = [
    "MissingCredentialsError",
    "MissingDependencyError",
    "UploadFailedError",
    "UploadInactiveError",
    "UploadResult",
    "preupload_and_wait_active",
    "upload_and_wait_active",
]


class ProviderUploadError(RuntimeError):
    """Base class for provider upload errors with context."""

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class UploadInactiveError(ProviderUploadError):
    """Raised when an uploaded file does not reach ACTIVE within the timeout."""


class UploadFailedError(ProviderUploadError):
    """Raised when the provider reports a terminal failure state.

    Attributes:
        state: Provider-reported terminal state (e.g., FAILED, ERROR, CANCELLED).
        details: Optional error payload or message from the provider.
    """

    def __init__(
        self, message: str, *, provider: str, state: str, details: Any | None
    ) -> None:
        """Initialize with provider context, terminal state, and details."""
        super().__init__(message, provider=provider)
        self.state = state
        self.details = details


class MissingCredentialsError(ProviderUploadError):
    """Raised when credentials are not available for the provider."""


class MissingDependencyError(ProviderUploadError):
    """Raised when the optional provider SDK is not installed."""


GOOGLE_PROVIDER: Final[str] = "google"


@runtime_checkable
class _ClientFiles(Protocol):
    def upload(self, *, file: str) -> Any: ...
    def get(self, *, name: str) -> Any: ...
    def list(self) -> Any: ...
    def delete(self, *, name: str) -> Any: ...


@runtime_checkable
class _GenAIClient(Protocol):
    @property
    def files(self) -> _ClientFiles: ...


@dataclass(frozen=True)
class UploadResult:
    """Structured upload result.

    Attributes:
        provider: Provider name (e.g., "google").
        id: Provider's stable identifier (often `name` or `uri`).
        uri: Canonical URI if available; falls back to `id`.
        state: Final observed state (e.g., "ACTIVE").
    """

    provider: str
    id: str
    uri: str
    state: str


def _google_client(*, api_key: str | None = None) -> _GenAIClient:
    """Create a Google GenAI client using resolved configuration or explicit key.

    Precedence for API key:
    1) explicit `api_key` argument if provided
    2) resolved configuration via `resolve_config()`
    3) environment variable `GEMINI_API_KEY`
    """
    try:
        import google.genai as genai
    except Exception as e:  # pragma: no cover - optional dependency
        raise MissingDependencyError(
            "google-genai SDK not installed", provider=GOOGLE_PROVIDER
        ) from e

    resolved_key: str | None = api_key

    if resolved_key is None:
        # Ensure .env file is loaded and try to obtain key from resolved config
        try:
            from pollux.config import resolve_config

            cfg = resolve_config()
            resolved_key = cfg.api_key
        except Exception:
            log.debug("Config resolution unavailable; falling back to environment only")

    if resolved_key is None:
        resolved_key = os.environ.get("GEMINI_API_KEY")

    if not resolved_key:
        raise MissingCredentialsError(
            "Missing API key for Google provider (set in config or GEMINI_API_KEY)",
            provider=GOOGLE_PROVIDER,
        )

    return genai.Client(api_key=resolved_key)


def _normalize_state(value: Any) -> str:
    """Return an uppercased provider-agnostic state name.

    Handles enum instances (with ``.name``), and string reprs like
    ``"FileState.ACTIVE"`` by taking the suffix after the last dot.
    """
    if value is None:
        return ""
    name = getattr(value, "name", None)
    if isinstance(name, str) and name:
        return name.upper()
    s = str(value).strip()
    if "." in s:
        s = s.split(".")[-1]
    return s.upper()


def preupload_and_wait_active(
    path: str | os.PathLike[str],
    *,
    provider: str = GOOGLE_PROVIDER,
    timeout_s: float = 120.0,
    poll_s: float = 2.0,
    max_poll_s: float | None = 10.0,
    backoff_factor: float = 1.5,
    jitter_s: float = 0.2,
    cleanup_on_timeout: bool = False,
    api_key: str | None = None,
) -> str:
    """Upload a local file and wait for ACTIVE; returns the file URI.

    Simplicity-first wrapper for apps/recipes. For structured details, see
    `upload_and_wait_active` which returns an `UploadResult`.
    """
    res = upload_and_wait_active(
        path,
        provider=provider,
        timeout_s=timeout_s,
        poll_s=poll_s,
        max_poll_s=max_poll_s,
        backoff_factor=backoff_factor,
        jitter_s=jitter_s,
        cleanup_on_timeout=cleanup_on_timeout,
        api_key=api_key,
    )
    return res.uri


def upload_and_wait_active(
    path: str | os.PathLike[str],
    *,
    provider: str = GOOGLE_PROVIDER,
    timeout_s: float = 120.0,
    poll_s: float = 2.0,
    max_poll_s: float | None = 10.0,
    backoff_factor: float = 1.5,
    jitter_s: float = 0.2,
    cleanup_on_timeout: bool = False,
    api_key: str | None = None,
) -> UploadResult:
    """Upload a local file via provider and wait until state is ACTIVE.

    Args:
        path: Local filesystem path to upload.
        provider: Provider key. Currently only "google" is supported.
        timeout_s: Total time to wait for the ACTIVE state.
        poll_s: Initial polling interval.
        max_poll_s: Upper bound for exponential backoff (None disables bound).
        backoff_factor: Multiplier applied to delay after each poll.
        jitter_s: Absolute jitter added each step (0 disables).
        cleanup_on_timeout: If True, attempt delete on timeout/failure.
        api_key: Explicit API key (overrides resolved config and env).

    Returns:
        UploadResult with provider, id, uri, and final state.

    Raises:
        FileNotFoundError: If `path` does not exist.
        NotImplementedError: If an unsupported provider is requested.
        MissingDependencyError: If the provider SDK is not installed.
        MissingCredentialsError: If credentials are not available.
        UploadFailedError: If the provider reports a terminal failure state.
        UploadInactiveError: If the file does not become ACTIVE in time.
    """
    # Validate input early for clearer UX
    fspath = os.fspath(path)
    if not Path(fspath).exists():
        raise FileNotFoundError(f"File not found: {fspath}")
    if provider != GOOGLE_PROVIDER:  # pragma: no cover - future providers
        raise NotImplementedError(f"Provider not supported: {provider}")

    client = _google_client(api_key=api_key)

    # Perform upload — SDK surfaces either `uri` or `name` depending on version.
    uploaded = client.files.upload(file=fspath)
    file_id = getattr(uploaded, "uri", None) or getattr(uploaded, "name", None)
    if not file_id:
        raise RuntimeError("Upload did not return a file identifier")

    start = time.monotonic()
    last_info: Any | None = None
    delay = max(float(poll_s), 0.01)
    seen_state: str | None = None
    while True:
        info: Any | None = None
        try:
            info = client.files.get(name=str(file_id))
        except Exception:
            # Fallback to list-scan for some SDK variants/backends
            try:
                files = list(client.files.list())
                info = next(
                    (
                        f
                        for f in files
                        if getattr(f, "name", None) == file_id
                        or getattr(f, "uri", None) == file_id
                    ),
                    None,
                )
                log.debug(
                    "provider_uploads: used list() fallback to locate file: %s", file_id
                )
            except Exception:
                info = None

        last_info = info or last_info
        state = (
            _normalize_state(getattr(info, "state", None)) if info is not None else ""
        )
        if state == "ACTIVE":
            rid = str(
                getattr(info, "name", None) or getattr(info, "uri", None) or file_id
            )
            ruri = str(getattr(info, "uri", None) or rid)
            return UploadResult(provider=provider, id=rid, uri=ruri, state=state)

        # Check for terminal failure states that will never become ACTIVE
        if state in ["FAILED", "ERROR", "CANCELLED"]:
            err = getattr(info, "error", None)
            # Support both dict-like and object-like error payloads
            if isinstance(err, dict):
                error_msg = err.get("message") or err.get("details") or str(err)
            else:
                error_msg = (
                    getattr(err, "message", None)
                    or getattr(err, "details", None)
                    or f"Upload failed with state: {state}"
                )
            # Optionally attempt cleanup
            if cleanup_on_timeout:
                with suppress(Exception):
                    client.files.delete(name=str(file_id))
            raise UploadFailedError(
                (
                    "File upload failed permanently: "
                    f"{error_msg} (file_id={file_id}, state={state})"
                ),
                provider=provider,
                state=state,
                details=err,
            )

        if time.monotonic() - start > timeout_s:
            # Optionally attempt cleanup
            if cleanup_on_timeout:
                with suppress(Exception):
                    client.files.delete(name=str(file_id))
            raise UploadInactiveError(
                (
                    "File did not become ACTIVE within "
                    f"{timeout_s}s (file_id={file_id}, state={state})"
                ),
                provider=provider,
            )

        # Log state transitions for better observability
        if state and state != seen_state:
            log.debug("provider_uploads: state changed: %s -> %s", seen_state, state)
            seen_state = state

        # Backoff with jitter
        time.sleep(max(delay, 0.01))
        if max_poll_s is not None:
            delay = min(delay * float(backoff_factor), float(max_poll_s))
        else:
            delay = delay * float(backoff_factor)
        # Apply small absolute jitter
        if jitter_s:
            delay = max(0.01, delay + (jitter_s * (0.5 - os.urandom(1)[0] / 255)))
