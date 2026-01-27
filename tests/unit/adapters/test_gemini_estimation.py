import pytest

from pollux.core.types import Source, TokenEstimate
from pollux.pipeline.tokens.adapters.gemini import GeminiEstimationAdapter

pytestmark = pytest.mark.unit


def test_gemini_image_compensation_bounds():
    adapter = GeminiEstimationAdapter()
    image_source = Source(
        source_type="file",  # images currently resolved as 'file' in SourceHandler
        identifier="test.jpg",
        mime_type="image/jpeg",
        size_bytes=500_000,
        content_loader=lambda: b"fake_image",
    )

    estimate = adapter.estimate(image_source)
    assert estimate.min_tokens >= 10
    assert 0.0 <= estimate.confidence <= 1.0
    assert estimate.min_tokens <= estimate.expected_tokens <= estimate.max_tokens


def test_aggregate_mixed_content():
    adapter = GeminiEstimationAdapter()
    text_est = TokenEstimate(100, 120, 140, 0.9)
    image_est = TokenEstimate(4000, 5000, 6000, 0.5)

    combined = adapter.aggregate([text_est, image_est])
    assert combined.min_tokens == 4100
    assert combined.expected_tokens == 5120
    assert combined.max_tokens == 6140
    assert combined.confidence <= 0.95
    assert combined.breakdown is not None and len(combined.breakdown) == 2
