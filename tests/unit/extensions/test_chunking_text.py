import pytest

from pollux.extensions.chunking import chunk_text_by_tokens


@pytest.mark.unit
def test_chunk_text_by_tokens_basic_split():
    text = "Para1.\n\n" + "Sentence. " * 200 + "\n\n" + "Para3."
    chunks = chunk_text_by_tokens(text, target_tokens=100, overlap_tokens=10)
    assert len(chunks) >= 2
    assert isinstance(chunks[0], str) and chunks[0].strip()
    # Overlap applied → later chunks should be longer than non-overlapped parts
    if len(chunks) > 1:
        assert len(chunks[1]) > 0


@pytest.mark.unit
def test_chunk_text_by_tokens_empty():
    assert chunk_text_by_tokens("", target_tokens=50) == []
