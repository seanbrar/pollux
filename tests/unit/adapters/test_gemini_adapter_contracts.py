from __future__ import annotations

import pytest

from pollux.core.types import Source
from pollux.pipeline.tokens.adapters.base import EstimationAdapter
from pollux.pipeline.tokens.adapters.gemini import GeminiEstimationAdapter

pytestmark = pytest.mark.contract


def test_adapter_conforms_to_protocol_runtime_checkable():
    adapter = GeminiEstimationAdapter()
    assert isinstance(adapter, EstimationAdapter)


def test_estimate_is_pure_and_deterministic():
    adapter = GeminiEstimationAdapter()
    s = Source(
        source_type="file",
        identifier="id",
        mime_type="application/octet-stream",
        size_bytes=123_456,
        content_loader=lambda: b"ignored",
    )

    a = adapter.estimate(s)
    b = adapter.estimate(s)

    # Deterministic: multiple calls yield identical results
    assert a == b
