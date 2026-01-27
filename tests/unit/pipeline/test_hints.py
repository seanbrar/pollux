"""Unit tests for hint capsules type contracts and immutability."""

import pytest

from pollux.core.execution_options import (
    CacheOptions,
    EstimationOptions,
    ResultOption,
)

pytestmark = pytest.mark.unit


class TestHintTypeContracts:
    """Verify hint types follow architectural contracts."""

    def test_cache_hint_is_frozen_and_immutable(self):
        """CacheOptions should be frozen dataclass with immutable behavior."""
        hint = CacheOptions("test-key")
        assert hint.deterministic_key == "test-key"
        assert hint.artifacts == ()
        assert hint.ttl_seconds is None
        assert hint.reuse_only is False

        # Should be frozen
        with pytest.raises(AttributeError):
            hint.deterministic_key = "new-key"  # type: ignore

    def test_cache_hint_with_all_fields(self):
        """CacheOptions should support all optional fields."""
        hint = CacheOptions(
            deterministic_key="conv:123",
            artifacts=("artifact1", "artifact2"),
            ttl_seconds=3600,
            reuse_only=True,
        )
        assert hint.deterministic_key == "conv:123"
        assert hint.artifacts == ("artifact1", "artifact2")
        assert hint.ttl_seconds == 3600
        assert hint.reuse_only is True

    def test_estimation_override_hint_is_frozen_and_immutable(self):
        """EstimationOptions should be frozen with defaults."""
        hint = EstimationOptions()
        assert hint.widen_max_factor == 1.0
        assert hint.clamp_max_tokens is None

        # Should be frozen
        with pytest.raises(AttributeError):
            hint.widen_max_factor = 2.0  # type: ignore

    def test_estimation_override_hint_with_overrides(self):
        """EstimationOptions should support conservative adjustments."""
        hint = EstimationOptions(widen_max_factor=1.5, clamp_max_tokens=16000)
        assert hint.widen_max_factor == 1.5
        assert hint.clamp_max_tokens == 16000

    def test_result_hint_is_frozen_and_immutable(self):
        """ResultOption should be frozen with defaults."""
        hint = ResultOption()
        assert hint.prefer_json_array is False

        # Should be frozen
        with pytest.raises(AttributeError):
            hint.prefer_json_array = True  # type: ignore

    def test_result_hint_with_json_preference(self):
        """ResultOption should support JSON array preference."""
        hint = ResultOption(prefer_json_array=True)
        assert hint.prefer_json_array is True

    def test_hints_are_hashable_for_deduplication(self):
        """All hint types should be hashable for use in sets/dicts."""
        cache1 = CacheOptions("key1")
        cache2 = CacheOptions("key1")
        cache3 = CacheOptions("key2")

        hint_set = {cache1, cache2, cache3}
        assert len(hint_set) == 2  # cache1 and cache2 should be equal

    def test_hints_have_meaningful_equality(self):
        """Hints with same values should be equal."""
        assert CacheOptions("key") == CacheOptions("key")
        assert CacheOptions("key1") != CacheOptions("key2")

        assert EstimationOptions(widen_max_factor=2.0) == EstimationOptions(
            widen_max_factor=2.0
        )
        assert EstimationOptions(widen_max_factor=1.0) != EstimationOptions(
            widen_max_factor=2.0
        )

        assert ResultOption(prefer_json_array=True) == ResultOption(
            prefer_json_array=True
        )
        assert ResultOption(prefer_json_array=False) != ResultOption(
            prefer_json_array=True
        )

    def test_hints_have_meaningful_string_representation(self):
        """Hints should have useful string representations for debugging."""
        cache = CacheOptions("test-key", artifacts=("a1",), ttl_seconds=3600)
        assert "test-key" in str(cache)
        assert "3600" in str(cache)

        estimation = EstimationOptions(widen_max_factor=1.5, clamp_max_tokens=10000)
        assert "1.5" in str(estimation)
        assert "10000" in str(estimation)

        result = ResultOption(prefer_json_array=True)
        assert "True" in str(result)
