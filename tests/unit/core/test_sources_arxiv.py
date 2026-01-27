import pytest

from pollux.core.sources import Source

pytestmark = pytest.mark.unit


class TestArxivNormalization:
    def test_bare_id_normalizes_to_pdf_url(self):
        s = Source.from_arxiv("1706.03762")
        assert s.identifier == "https://arxiv.org/pdf/1706.03762.pdf"
        assert s.mime_type == "application/pdf"
        assert s.size_bytes == 0
        # Content loader returns bytes; allow bytearray for flexibility
        assert isinstance(s.content_loader(), bytes | bytearray)

    def test_legacy_id_with_version(self):
        s = Source.from_arxiv("cs.CL/9901001v2")
        assert s.identifier == "https://arxiv.org/pdf/cs.CL/9901001v2.pdf"

    def test_abs_url_with_version(self):
        s = Source.from_arxiv("https://arxiv.org/abs/1706.03762v5")
        assert s.identifier == "https://arxiv.org/pdf/1706.03762v5.pdf"

    def test_pdf_url_without_suffix_gets_pdf(self):
        s = Source.from_arxiv("https://arxiv.org/pdf/1706.03762v5")
        assert s.identifier == "https://arxiv.org/pdf/1706.03762v5.pdf"

    def test_pdf_url_with_query_strips_query(self):
        s = Source.from_arxiv("https://arxiv.org/pdf/1706.03762v5.pdf?download=1")
        assert s.identifier == "https://arxiv.org/pdf/1706.03762v5.pdf"

    def test_invalid_host_raises(self):
        with pytest.raises(ValueError):
            Source.from_arxiv("https://example.com/abs/1706.03762")

    def test_invalid_identifier_raises(self):
        with pytest.raises(ValueError):
            Source.from_arxiv("not-an-arxiv-id")


class TestYouTubeDetection:
    def test_youtube_positive_cases(self):
        assert Source._is_youtube_url("https://www.youtube.com/watch?v=abc123")
        assert Source._is_youtube_url("https://youtu.be/abc123")
        assert Source._is_youtube_url("https://youtube.com/embed/abc123")

    def test_youtube_negative_cases(self):
        assert not Source._is_youtube_url("https://example.com/watch?v=abc")
        assert not Source._is_youtube_url("youtub.e/abc")
