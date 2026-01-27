import pytest

from pollux.extensions.chunking import (
    TranscriptSegment,
    chunk_transcript_by_tokens,
)


@pytest.mark.unit
def test_chunk_transcript_by_tokens_basic():
    segments = [
        TranscriptSegment(0, 5, "Hello world."),
        TranscriptSegment(5, 10, "This is a longer sentence " * 20),
        TranscriptSegment(10, 15, "Wrap up."),
    ]
    chunks = chunk_transcript_by_tokens(segments, target_tokens=60, overlap_tokens=10)
    assert len(chunks) >= 1
    for ch in chunks:
        assert ch.text.strip()
        assert ch.start_sec <= ch.end_sec
        assert len(ch.segments) >= 1


@pytest.mark.unit
def test_chunk_transcript_by_tokens_empty():
    assert chunk_transcript_by_tokens([], target_tokens=50) == []
