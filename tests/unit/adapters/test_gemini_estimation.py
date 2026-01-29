from __future__ import annotations

import math

import pytest

from pollux.core.types import Source, TokenEstimate
from pollux.pipeline.tokens.adapters.gemini import (
    GeminiBiases,
    GeminiEstimationAdapter,
)

pytestmark = pytest.mark.unit


def make_source(source_type: str, mime: str, size: int) -> Source:
    return Source(
        source_type=source_type,  # type: ignore[arg-type]
        identifier="id",
        mime_type=mime,
        size_bytes=size,
        content_loader=lambda: b"",
    )


def test_effective_type_file_image_and_video():
    adapter = GeminiEstimationAdapter(GeminiBiases.v1_august_2025())

    img = make_source("file", "image/jpeg", 500_000)
    vid = make_source("file", "video/mp4", 2_000_000)
    other = make_source("file", "application/octet-stream", 100_000)

    img_est = adapter.estimate(img)
    vid_est = adapter.estimate(vid)
    other_est = adapter.estimate(other)

    assert img_est.expected_tokens > other_est.expected_tokens
    assert vid_est.expected_tokens > other_est.expected_tokens


def test_confidence_bands_simple_thresholds():
    adapter = GeminiEstimationAdapter(GeminiBiases.v1_august_2025())

    # Text -> confidence 0.9 -> ±10%
    text = make_source("text", "text/plain", 4_200)  # ~1000 base tokens before bias
    t = adapter.estimate(text)
    span = t.max_tokens - t.expected_tokens
    # Allow 1 token rounding wiggle
    assert abs(span - int(t.expected_tokens * 0.10)) <= 1

    # Image -> confidence 0.5 -> ±30%
    image = make_source("file", "image/png", 500_000)
    i = adapter.estimate(image)
    span_i = i.max_tokens - i.expected_tokens
    assert abs(span_i - int(i.expected_tokens * 0.30)) <= 2


def test_aggregate_sums_and_reduces_confidence():
    adapter = GeminiEstimationAdapter()
    a = TokenEstimate(100, 120, 140, 0.9)
    b = TokenEstimate(400, 500, 600, 0.5)

    total = adapter.aggregate([a, b])

    assert total.min_tokens == 500
    assert total.expected_tokens == 620
    assert total.max_tokens == 740
    # Reduced below the minimum component confidence
    assert math.isclose(total.confidence, 0.5 * 0.9, rel_tol=0.01)
    assert total.breakdown is not None and len(total.breakdown) == 2


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
