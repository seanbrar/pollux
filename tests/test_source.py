"""Source boundary tests: factory construction, validation, and normalization."""

from __future__ import annotations

from typing import Any

import pytest

from pollux.errors import SourceError
from pollux.source import Source

pytestmark = pytest.mark.unit


def test_source_from_file_rejects_missing_file(tmp_path: Any) -> None:
    """from_file() should fail clearly for non-existent paths."""
    missing = tmp_path / "does_not_exist.txt"

    with pytest.raises(SourceError) as exc:
        Source.from_file(missing)

    assert "not found" in str(exc.value).lower()


@pytest.mark.parametrize("invalid_ref", ["", "   "])
def test_source_from_arxiv_rejects_invalid_refs(invalid_ref: str) -> None:
    """from_arxiv() should fail for empty/whitespace strings."""
    with pytest.raises(SourceError):
        Source.from_arxiv(invalid_ref)


@pytest.mark.parametrize(
    "arxiv_id",
    [
        "2301.07041",
        "1706.03762v7",
        "hep-th/9901001",
        "math-ph/0301001v2",
    ],
)
def test_source_from_arxiv_normalizes_to_canonical_pdf_url(arxiv_id: str) -> None:
    """arXiv ids and URLs normalize to canonical PDF URLs and stable loaders."""
    expected = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    refs = [
        arxiv_id,
        f"https://arxiv.org/abs/{arxiv_id}",
        f"https://arxiv.org/pdf/{arxiv_id}.pdf",
    ]
    for ref in refs:
        source = Source.from_arxiv(ref)
        assert source.source_type == "arxiv"
        assert source.identifier == expected
        assert source.mime_type == "application/pdf"
        assert source.content_loader() == expected.encode("utf-8")


def test_source_from_arxiv_rejects_non_arxiv_urls() -> None:
    """Only arxiv.org URLs should be accepted."""
    with pytest.raises(SourceError):
        Source.from_arxiv("https://example.com/abs/1706.03762")


def test_with_gemini_video_settings_stores_validated_settings() -> None:
    """Gemini video settings should be stored and re-exposed for Gemini only."""
    source = Source.from_youtube(
        "https://www.youtube.com/watch?v=abc123"
    ).with_gemini_video_settings(start_offset="10s", end_offset="20s", fps=1.0)

    assert source.gemini_video_settings_for("gemini") == {
        "start_offset": "10s",
        "end_offset": "20s",
        "fps": 1.0,
    }


def test_gemini_video_settings_for_scopes_to_gemini_provider() -> None:
    """Gemini video settings should only affect Gemini requests."""
    source = Source.from_youtube(
        "https://www.youtube.com/watch?v=abc123"
    ).with_gemini_video_settings(fps=1.0)

    assert source.gemini_video_settings_for("gemini") == {"fps": 1.0}
    assert source.gemini_video_settings_for("openai") is None
    assert source.gemini_video_settings_for(None) is None


def test_with_gemini_video_settings_rejects_non_video_source() -> None:
    """Gemini video settings should fail fast on non-video sources."""
    source = Source.from_text("hello")
    with pytest.raises(SourceError, match="video source"):
        source.with_gemini_video_settings(fps=1.0)


def test_with_gemini_video_settings_requires_at_least_one_value() -> None:
    """An empty Gemini video settings payload should be rejected."""
    source = Source.from_youtube("https://www.youtube.com/watch?v=abc123")
    with pytest.raises(SourceError, match="Provide at least one"):
        source.with_gemini_video_settings()


@pytest.mark.parametrize("bad_fps", [0, -1, 25, True, "fast"])
def test_with_gemini_video_settings_rejects_invalid_fps(bad_fps: Any) -> None:
    """fps should be validated before any provider call is attempted."""
    source = Source.from_youtube("https://www.youtube.com/watch?v=abc123")
    with pytest.raises(SourceError, match="fps"):
        source.with_gemini_video_settings(fps=bad_fps)


def test_with_gemini_video_settings_requires_non_empty_offsets() -> None:
    """Offsets should fail fast when blank."""
    source = Source.from_youtube("https://www.youtube.com/watch?v=abc123")
    with pytest.raises(SourceError, match="start_offset"):
        source.with_gemini_video_settings(start_offset="  ")
    with pytest.raises(SourceError, match="end_offset"):
        source.with_gemini_video_settings(end_offset="")


def test_with_gemini_video_settings_does_not_mutate_original() -> None:
    """with_gemini_video_settings returns a new Source; the original is unchanged."""
    original = Source.from_youtube("https://www.youtube.com/watch?v=abc123")
    modified = original.with_gemini_video_settings(fps=1.0)

    assert original.gemini_video_settings_for("gemini") is None
    assert modified.gemini_video_settings_for("gemini") == {"fps": 1.0}


def test_with_gemini_video_settings_returns_copied_payloads() -> None:
    """Returned payload dicts should be detached from the stored source state."""
    source = Source.from_youtube(
        "https://www.youtube.com/watch?v=abc123"
    ).with_gemini_video_settings(fps=1.0)

    payload = source.gemini_video_settings_for("gemini")
    assert payload is not None
    payload["fps"] = 99.0

    assert source.gemini_video_settings_for("gemini") == {"fps": 1.0}


def test_with_gemini_url_context_stores_provider_hint() -> None:
    """Gemini URL Context should be a Gemini-scoped URI source hint."""
    source = Source.from_uri(
        "https://example.com/page",
        mime_type="text/html",
    ).with_gemini_url_context()

    assert source.provider_hints_for("gemini") == {"url_context": {}}
    assert source.provider_hints_for("openai") is None


@pytest.mark.parametrize(
    "source",
    [
        Source.from_text("hello"),
        Source.from_uri("gs://bucket/object", mime_type="text/plain"),
    ],
)
def test_with_gemini_url_context_rejects_invalid_sources(source: Source) -> None:
    """Gemini URL Context should be limited to HTTP(S) URI sources."""
    with pytest.raises(SourceError):
        source.with_gemini_url_context()
