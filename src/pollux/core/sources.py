"""Source helpers: explicit directory expansion and file walking.

These helpers restore feature completeness for directory inputs while keeping
the core pipeline explicit and type-safe. End-users can call these utilities to
materialize `Source` objects prior to invoking the pipeline/frontdoor.
"""

from __future__ import annotations

import dataclasses
import mimetypes
from pathlib import Path
import re
import typing
from typing import TYPE_CHECKING, Final
from urllib.parse import urlparse, urlunparse

from ._validation import _require, _require_zero_arg_callable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


_EXCLUDE_DIRS: Final[set[str]] = {
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".venv",
    "venv",
    ".env",
    "build",
    "dist",
    ".tox",
    ".coverage",
}

# Precompiled arXiv identifier patterns for reuse and consistency
MODERN_ARXIV_RE: Final[re.Pattern[str]] = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$")
"""Matches modern arXiv identifiers like '2301.12345' or '2301.12345v2'."""

LEGACY_ARXIV_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z]+(?:\.[A-Za-z]+)?/\d{7}(?:v\d+)?$"
)
"""Matches legacy arXiv identifiers like 'cs/9901001' or 'math.PR/9901001v3'."""


def _is_arxiv_identifier(ident: str) -> bool:
    ident = ident.strip("/")
    return bool(MODERN_ARXIV_RE.match(ident) or LEGACY_ARXIV_RE.match(ident))


def _is_arxiv_host(host: str) -> bool:
    """Return True for hosts that are definitively part of arXiv.

    Accepts `arxiv.org`, its subdomains (e.g., `foo.arxiv.org`), and the
    historical `export.arxiv.org`. Rejects lookalikes like `arxiv.org.evil.com`.
    """
    h = (host or "").lower()
    return h == "arxiv.org" or h == "export.arxiv.org" or h.endswith(".arxiv.org")


@dataclasses.dataclass(frozen=True, slots=True)
class Source:
    """A structured representation of a single input source.

    Content access is lazy via the `content_loader` callable to optimize
    memory usage, ensuring content is only loaded when needed.
    """

    source_type: typing.Literal["text", "youtube", "arxiv", "file", "uri"]
    identifier: str | Path  # The original path, URL, or text identifier
    mime_type: str
    size_bytes: int
    content_loader: Callable[[], bytes]  # A function to get content on demand

    def __post_init__(self) -> None:
        """Validate Source invariants and loader signature."""
        _require(
            condition=self.source_type in ("text", "youtube", "arxiv", "file", "uri"),
            message=(
                "must be one of ['text','youtube','arxiv','file','uri'], got "
                f"{self.source_type!r}"
            ),
            field_name="source_type",
        )
        _require(
            condition=isinstance(self.identifier, str | Path),
            message="must be str | Path",
            field_name="identifier",
            exc=TypeError,
        )
        # Additional validation for Path identifiers
        if isinstance(self.identifier, Path):
            _require(
                condition=str(self.identifier).strip() != "",
                message="Path cannot be empty",
                field_name="identifier",
            )
        elif isinstance(self.identifier, str):
            _require(
                condition=self.identifier.strip() != "",
                message="cannot be empty string",
                field_name="identifier",
            )

        _require(
            condition=isinstance(self.mime_type, str) and self.mime_type.strip() != "",
            message="must be a non-empty str",
            field_name="mime_type",
            exc=TypeError,
        )
        _require(
            condition=isinstance(self.size_bytes, int) and self.size_bytes >= 0,
            message="must be an int >= 0",
            field_name="size_bytes",
        )

        # Use the dedicated helper for callable validation
        _require_zero_arg_callable(self.content_loader, "content_loader")

    # --- Ergonomic constructors for common cases ---
    @classmethod
    def from_text(cls, content: str, identifier: str | None = None) -> Source:
        """Create a text `Source` from a string.

        Args:
            content: Text content to analyze.
            identifier: Optional identifier; defaults to a snippet of the content.

        Returns:
            A `Source` representing UTF-8 encoded text.
        """
        _require(
            condition=isinstance(content, str),
            message="must be a str",
            field_name="content",
            exc=TypeError,
        )
        encoded = content.encode("utf-8")
        display = identifier if identifier is not None else content[:100]
        return cls(
            source_type="text",
            identifier=display,
            mime_type="text/plain",
            size_bytes=len(encoded),
            content_loader=lambda: encoded,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> Source:
        """Create a file `Source` from a local filesystem path.

        Args:
            path: Path to a local file.

        Returns:
            A `Source` that lazily loads the file bytes.
        """
        file_path = Path(path)
        _require(
            condition=file_path.is_file(),
            message="path must point to an existing file",
            field_name="path",
        )

        mime_type, _ = mimetypes.guess_type(str(file_path))
        return cls(
            source_type="file",
            identifier=file_path,
            mime_type=mime_type or "application/octet-stream",
            size_bytes=file_path.stat().st_size,
            content_loader=lambda: file_path.read_bytes(),
        )

    @classmethod
    def from_youtube(cls, url: str) -> Source:
        """Create a YouTube `Source` that passes the URL directly to the API.

        The URL is kept intact as the `identifier`. No network I/O occurs.
        """
        _require(
            condition=isinstance(url, str),
            message="must be a str",
            field_name="url",
            exc=TypeError,
        )
        normalized = url.strip()
        _require(
            condition=cls._is_youtube_url(normalized),
            message="invalid YouTube URL; expected formats like https://www.youtube.com/watch?v=... or https://youtu.be/...",
            field_name="url",
        )
        encoded = normalized.encode("utf-8")
        return cls(
            source_type="youtube",
            identifier=normalized,
            mime_type="video/youtube",
            size_bytes=0,
            content_loader=lambda: encoded,
        )

    @classmethod
    def from_arxiv(cls, ref: str) -> Source:
        """Create an arXiv PDF `Source` from an id or URL.

        Accepts bare ids (e.g., "1706.03762", "cs.CL/9901001"), `abs` URLs,
        and `pdf` URLs. Normalizes to a canonical PDF URL.
        """
        _require(
            condition=isinstance(ref, str),
            message="must be a str",
            field_name="ref",
            exc=TypeError,
        )
        normalized_url = cls._normalize_arxiv_to_pdf_url(ref.strip())
        encoded = normalized_url.encode("utf-8")
        return cls(
            source_type="arxiv",
            identifier=normalized_url,
            mime_type="application/pdf",
            size_bytes=0,
            content_loader=lambda: encoded,
        )

    @classmethod
    def from_uri(cls, uri: str, mime_type: str) -> Source:
        """Create a generic URI-backed `Source` with explicit MIME type.

        Prefer `from_youtube()` and `from_arxiv()` for those known shapes; this
        constructor is for other URIs where the caller knows the MIME type.

        Experimental: Support for arbitrary non-YouTube/arXiv URIs may evolve.
        This method treats the URI as a direct provider reference (no I/O).
        """
        _require(
            condition=isinstance(uri, str),
            message="must be a str",
            field_name="uri",
            exc=TypeError,
        )
        _require(
            condition=isinstance(mime_type, str) and mime_type.strip() != "",
            message="must be a non-empty str",
            field_name="mime_type",
            exc=TypeError,
        )
        # Offer helpful redirection to specialized constructors
        if cls._is_youtube_url(uri):
            raise ValueError(
                "YouTube URL detected. Use Source.from_youtube(url) for clarity."
            )
        if cls._looks_like_arxiv(uri):
            raise ValueError(
                "arXiv reference detected. Use Source.from_arxiv(ref) for normalization."
            )
        encoded = uri.encode("utf-8")
        return cls(
            source_type="uri",
            identifier=uri,
            mime_type=mime_type,
            size_bytes=0,
            content_loader=lambda: encoded,
        )

    # --- Pure helpers (kept close to Source for testability) ---
    @staticmethod
    def _is_youtube_url(url: str) -> bool:
        u = url.lower()
        if not (u.startswith(("http://", "https://"))):
            return False
        return (
            "youtube.com/watch?v=" in u
            or "youtu.be/" in u
            or "youtube.com/embed/" in u
            or "youtube.com/v/" in u
            or ("youtube.com/" in u and "v=" in u)
        )

    @staticmethod
    def _looks_like_arxiv(s: str) -> bool:
        u = s.strip()
        ul = u.lower()
        # Any obvious arXiv host reference
        if "arxiv.org/" in ul or "export.arxiv.org/" in ul:
            return True

        # Reuse precompiled patterns for consistency and performance
        return bool(MODERN_ARXIV_RE.match(u) or LEGACY_ARXIV_RE.match(u))

    @staticmethod
    def _normalize_arxiv_to_pdf_url(ref: str) -> str:
        """Normalize arXiv id or URL into canonical PDF URL.

        Supported inputs:
        - bare id: 1706.03762, 1706.03762v5
        - legacy id with category: cs.CL/9901001 (with optional version)
        - abs URL: https://arxiv.org/abs/1706.03762[vN]
        - pdf URL: https://arxiv.org/pdf/1706.03762[vN].pdf

        Returns canonical: https://arxiv.org/pdf/<id>.pdf (preserving version).
        Raises ValueError for invalid shapes.
        """
        u = ref.strip()
        if u == "":
            raise ValueError("arXiv reference cannot be empty")

        lower = u.lower()
        base = "https://arxiv.org/pdf/"

        # URL inputs: accept arXiv hosts and /pdf/ or /abs/ shapes
        if lower.startswith(("http://", "https://")):
            parsed = urlparse(u)
            host = (parsed.netloc or "").lower()
            if not _is_arxiv_host(host):
                raise ValueError("Unsupported arXiv URL host")

            path = parsed.path or ""
            if "/pdf/" in path:
                # Already a PDF path; strip query/fragment and ensure .pdf suffix on the path
                new_path = path if path.endswith(".pdf") else (path + ".pdf")
                # Canonicalize host to arxiv.org for consistency
                return urlunparse((parsed.scheme, "arxiv.org", new_path, "", "", ""))

            if "/abs/" in path:
                # Extract identifier segment after /abs/, strip trailing slashes
                try:
                    ident = path.split("/abs/", 1)[1].strip("/")
                except IndexError:
                    ident = ""
                _require(
                    condition=bool(ident) and _is_arxiv_identifier(ident),
                    message="invalid arXiv abs URL",
                    field_name="ref",
                )
                return f"{base}{ident}.pdf"

            raise ValueError("Unsupported arXiv URL; expected /abs/ or /pdf/")

        # Bare identifiers: modern or legacy formats with optional version
        ident = u.strip("/")
        if not _is_arxiv_identifier(ident):
            raise ValueError(
                "Invalid arXiv identifier; expected e.g. '1706.03762' or 'cs.CL/9901001'"
            )
        return f"{base}{ident}.pdf"


def iter_files(directory: str | Path) -> Iterable[Path]:
    """Yield all files under `directory` recursively with stable ordering.

    Excludes common VCS/virtualenv/build directories for predictable behavior.

    Raises:
        ValueError: If `directory` does not exist or is not a directory.
    """
    import os

    root_path = Path(directory)
    if not root_path.is_dir():
        raise ValueError("directory must be an existing directory")

    def _walk() -> Iterable[Path]:
        for root, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in sorted(dirnames) if d not in _EXCLUDE_DIRS]
            for fname in sorted(filenames):
                p = Path(root) / fname
                try:
                    if p.is_file():
                        yield p
                except OSError:
                    continue

    return _walk()


def sources_from_directory(directory: str | Path) -> tuple[Source, ...]:
    """Return `Source` objects for all files under `directory` (recursive).

    Uses `Source.from_file` for MIME detection and lazy loading.

    Raises:
        ValueError: If `directory` does not exist or is not a directory.
    """
    return tuple(Source.from_file(p) for p in iter_files(directory))
