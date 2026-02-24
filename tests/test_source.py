"""Source boundary tests: factory construction, validation, and normalization."""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
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


@given(
    arxiv_id=st.one_of(
        st.from_regex(r"\d{4}\.\d{4,5}(?:v\d+)?", fullmatch=True),
        st.from_regex(
            r"[a-z\-]+(?:\.[a-z\-]+)?/\d{7}(?:v\d+)?",
            fullmatch=True,
        ),
    )
)
@settings(max_examples=10, deadline=None, derandomize=True)
def test_source_from_arxiv_normalizes_to_canonical_pdf_url(arxiv_id: str) -> None:
    """Property: arXiv refs normalize to canonical PDF URLs and stable loaders."""
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
