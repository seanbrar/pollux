"""Source: Explicit input types for Pollux."""

from __future__ import annotations

from collections.abc import Callable  # noqa: TC003 - used at runtime in dataclass
from dataclasses import dataclass, replace
import hashlib
import json
import mimetypes
from pathlib import Path
import re
from typing import Any, Literal
from urllib.parse import urlparse

from pollux.errors import SourceError

SourceType = Literal["text", "file", "youtube", "arxiv", "uri", "json"]
_ARXIV_HOSTS = {"arxiv.org", "www.arxiv.org"}
_ARXIV_ID_RE = re.compile(
    r"^(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[a-z\-]+)?/\d{7}(?:v\d+)?)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ProviderHint:
    """Immutable provider-scoped source extension."""

    provider: str
    name: str
    payload: tuple[tuple[str, str | float], ...]

    def payload_dict(self) -> dict[str, str | float]:
        """Convert the immutable payload back to a dictionary."""
        return dict(self.payload)


@dataclass(frozen=True, slots=True)
class Source:
    """A structured representation of a single input source."""

    source_type: SourceType
    identifier: str
    mime_type: str
    size_bytes: int
    content_loader: Callable[[], bytes]
    provider_hints: tuple[ProviderHint, ...] = ()

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
    def from_json(
        cls, data: dict[str, Any] | Any, *, identifier: str | None = None
    ) -> Source:
        """Create a Source from a JSON-serializable object.

        Args:
            data: A dictionary or object to serialize into a JSON string. If the object
                has a `model_dump()` method (like Pydantic models), it will be used.
            identifier: Display label. Defaults to "json-data".
        """
        if hasattr(data, "model_dump") and callable(data.model_dump):
            data = data.model_dump()

        try:
            content = json.dumps(data).encode("utf-8")
        except TypeError as exc:
            raise SourceError(f"Data is not JSON serializable: {exc}") from exc

        ident = identifier or "json-data"
        return cls(
            source_type="json",
            identifier=ident,
            mime_type="application/json",
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

    def _content_hash(self) -> str:
        """Compute SHA256 hash of raw content bytes."""
        content = self.content_loader()
        return hashlib.sha256(content).hexdigest()

    def gemini_video_settings_for(
        self, provider: str | None
    ) -> dict[str, str | float] | None:
        """Return Gemini video settings when the active provider can use them."""
        provider_hints = self.provider_hints_for(provider)
        if provider_hints is None:
            return None
        return provider_hints.get("video_metadata")

    def provider_hints_for(
        self, provider: str | None
    ) -> dict[str, dict[str, str | float]] | None:
        """Return immutable provider hints as plain dictionaries for transport."""
        if provider is None:
            return None

        hints = {
            hint.name: hint.payload_dict()
            for hint in self.provider_hints
            if hint.provider == provider
        }
        return hints or None

    def cache_identity_hash(self, *, provider: str | None = None) -> str:
        """Compute SHA256 hash for cache identity.

        Includes provider-visible source semantics such as Gemini video settings.
        Falls back to raw content hash when no provider-specific settings apply,
        preserving backward-compatible cache keys.
        """
        provider_hints = self.provider_hints_for(provider)
        if provider_hints is None:
            return self._content_hash()
        combined = (
            self._content_hash()
            + "|"
            + json.dumps(
                provider_hints,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def with_gemini_video_settings(
        self,
        *,
        start_offset: str | None = None,
        end_offset: str | None = None,
        fps: float | None = None,
    ) -> Source:
        """Return a copy with validated Gemini video controls attached.

        Pollux keeps this API provider-specific and stable even if Google's
        underlying wire fields evolve. The Gemini adapter maps these settings
        to the current SDK request shape. These settings only affect Gemini
        requests and Gemini explicit-cache identity.
        """
        if not self._is_video_source():
            raise SourceError(
                "Gemini video settings require a video source "
                "(local video file, video URI, or YouTube URL)"
            )

        validated_start_offset: str | None = None
        validated_end_offset: str | None = None
        validated_fps: float | None = None

        if start_offset is not None:
            if not isinstance(start_offset, str) or not start_offset.strip():
                raise SourceError("start_offset must be a non-empty string")
            validated_start_offset = start_offset

        if end_offset is not None:
            if not isinstance(end_offset, str) or not end_offset.strip():
                raise SourceError("end_offset must be a non-empty string")
            validated_end_offset = end_offset

        if fps is not None:
            if isinstance(fps, bool) or not isinstance(fps, (int, float)):
                raise SourceError("fps must be a number")
            fps_value = float(fps)
            if fps_value <= 0 or fps_value > 24:
                raise SourceError("fps must be > 0 and <= 24")
            validated_fps = fps_value

        if (
            validated_start_offset is None
            and validated_end_offset is None
            and validated_fps is None
        ):
            raise SourceError(
                "Provide at least one Gemini video setting: "
                "start_offset, end_offset, or fps"
            )

        return replace(
            self,
            provider_hints=self._with_provider_hint(
                provider="gemini",
                name="video_metadata",
                payload={
                    k: v
                    for k, v in (
                        ("start_offset", validated_start_offset),
                        ("end_offset", validated_end_offset),
                        ("fps", validated_fps),
                    )
                    if v is not None
                },
            ),
        )

    def _is_video_source(self) -> bool:
        """Return True when Gemini video controls can apply to this source."""
        return self.source_type == "youtube" or self.mime_type.startswith("video/")

    def _with_provider_hint(
        self,
        *,
        provider: str,
        name: str,
        payload: dict[str, str | float],
    ) -> tuple[ProviderHint, ...]:
        """Return provider hints with one named hint replaced or added."""
        hint = ProviderHint(
            provider=provider,
            name=name,
            payload=tuple(sorted(payload.items())),
        )
        existing = tuple(
            item
            for item in self.provider_hints
            if not (item.provider == provider and item.name == name)
        )
        return (*existing, hint)
