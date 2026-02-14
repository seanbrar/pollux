"""Source: Explicit input types for Pollux."""

from __future__ import annotations

from collections.abc import Callable  # noqa: TC003 - used at runtime in dataclass
from dataclasses import dataclass
import hashlib
import mimetypes
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlparse

from pollux.errors import SourceError

SourceType = Literal["text", "file", "youtube", "arxiv", "uri"]
_ARXIV_HOSTS = {"arxiv.org", "www.arxiv.org"}
_ARXIV_ID_RE = re.compile(
    r"^(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[a-z\-]+)?/\d{7}(?:v\d+)?)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Source:
    """A structured representation of a single input source."""

    source_type: SourceType
    identifier: str
    mime_type: str
    size_bytes: int
    content_loader: Callable[[], bytes]

    @classmethod
    def from_text(cls, text: str, *, identifier: str | None = None) -> Source:
        """Create a Source from text content.

        Args:
            text: The text content.
            identifier: Display label. Defaults to the first 50 characters of *text*.
        """
        content = text.encode("utf-8")
        ident = identifier or text[:50]
        return cls(
            source_type="text",
            identifier=ident,
            mime_type="text/plain",
            size_bytes=len(content),
            content_loader=lambda: content,
        )

    @classmethod
    def from_file(cls, path: str | Path, *, mime_type: str | None = None) -> Source:
        """Create a Source from a local file.

        Args:
            path: Path to the file. Must exist or ``SourceError`` is raised.
            mime_type: MIME type override. Auto-detected from extension when *None*.
        """
        p = Path(path)
        if not p.exists():
            raise SourceError(f"File not found: {p}")

        mt = mime_type or mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        size = p.stat().st_size

        def loader() -> bytes:
            return p.read_bytes()

        return cls(
            source_type="file",
            identifier=str(p),
            mime_type=mt,
            size_bytes=size,
            content_loader=loader,
        )

    @classmethod
    def from_youtube(cls, url: str) -> Source:
        """Create a Source from a YouTube URL reference (no download)."""
        encoded = f"youtube:{url}".encode()
        return cls(
            source_type="youtube",
            identifier=url,
            mime_type="video/mp4",
            size_bytes=0,
            content_loader=lambda: encoded,
        )

    @classmethod
    def from_uri(
        cls, uri: str, *, mime_type: str = "application/octet-stream"
    ) -> Source:
        """Create a Source from a URI.

        Args:
            uri: Remote URI (e.g. ``gs://`` or ``https://``).
            mime_type: MIME type. Defaults to ``application/octet-stream``.
        """
        encoded = f"uri:{mime_type}:{uri}".encode()
        return cls(
            source_type="uri",
            identifier=uri,
            mime_type=mime_type,
            size_bytes=0,
            content_loader=lambda: encoded,
        )

    @classmethod
    def from_arxiv(cls, ref: str) -> Source:
        """Create an arXiv PDF Source from an arXiv ID or URL.

        Args:
            ref: An arXiv ID (e.g. ``"2301.07041"``) or full arXiv URL.
        """
        if not isinstance(ref, str):
            raise TypeError("ref must be a str")

        normalized_url = cls._normalize_arxiv_to_pdf_url(ref.strip())
        encoded = normalized_url.encode("utf-8")
        return cls(
            source_type="arxiv",
            identifier=normalized_url,
            mime_type="application/pdf",
            size_bytes=0,
            content_loader=lambda: encoded,
        )

    @staticmethod
    def _normalize_arxiv_to_pdf_url(ref: str) -> str:
        """Normalize arXiv id or URL to canonical PDF URL."""
        if not ref:
            raise SourceError("arXiv reference cannot be empty")

        arxiv_id = ref
        if ref.startswith(("http://", "https://")):
            parsed = urlparse(ref)
            host = parsed.netloc.lower()
            if host not in _ARXIV_HOSTS:
                raise SourceError(f"Expected arxiv.org URL, got: {parsed.netloc}")

            path = parsed.path.strip("/")
            if path.startswith("abs/"):
                arxiv_id = path[len("abs/") :]
            elif path.startswith("pdf/"):
                arxiv_id = path[len("pdf/") :]
            else:
                raise SourceError(f"Unsupported arXiv URL path: {parsed.path}")

        if arxiv_id.endswith(".pdf"):
            arxiv_id = arxiv_id[:-4]

        arxiv_id = arxiv_id.strip("/")
        if not _ARXIV_ID_RE.match(arxiv_id):
            raise SourceError(f"Invalid arXiv id: {arxiv_id}")

        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    def content_hash(self) -> str:
        """Compute SHA256 hash of content for cache identity."""
        content = self.content_loader()
        return hashlib.sha256(content).hexdigest()
