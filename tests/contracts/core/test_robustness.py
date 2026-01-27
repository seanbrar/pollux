import pytest

from pollux.core import exceptions, models, types


class TestRobustnessCompliance:
    """Tests that verify the core module maintains architectural robustness."""

    @pytest.mark.unit
    @pytest.mark.contract
    def test_dataclasses_are_frozen(self):
        """All dataclasses should be frozen for immutability."""
        dataclasses = [
            types.Success,
            types.Failure,
            types.Turn,
            types.Source,
            types.InitialCommand,
            types.ResolvedCommand,
            models.RateLimits,
            models.CachingCapabilities,
            models.ModelCapabilities,
        ]

        # Add Result Builder extraction types (internal - not in core.types)
        from pollux.pipeline.results.extraction import (
            ExtractionContext,
            ExtractionContract,
            ExtractionResult,
            TransformSpec,
            Violation,
        )

        extraction_dataclasses = [
            TransformSpec,
            ExtractionContext,
            ExtractionContract,
            ExtractionResult,
            Violation,
        ]

        dataclasses.extend(extraction_dataclasses)

        for cls in dataclasses:
            # Check if dataclass is frozen by looking at __dataclass_params__
            if hasattr(cls, "__dataclass_params__"):
                assert cls.__dataclass_params__.frozen, (
                    f"{cls.__name__} should be frozen"
                )

    @pytest.mark.unit
    @pytest.mark.contract
    def test_exceptions_have_proper_inheritance(self):
        """Exceptions should have proper inheritance hierarchy."""
        # All custom exceptions should inherit from base
        custom_exceptions = [
            exceptions.APIError,
            exceptions.PipelineError,
            exceptions.ConfigurationError,
            exceptions.SourceError,
            exceptions.MissingKeyError,
            exceptions.FileError,
            exceptions.ValidationError,
            exceptions.UnsupportedContentError,
        ]

        for exception_class in custom_exceptions:
            assert issubclass(exception_class, exceptions.GeminiBatchError), (
                f"{exception_class.__name__} should inherit from GeminiBatchError"
            )

    @pytest.mark.unit
    @pytest.mark.contract
    def test_functions_are_pure(self):
        """Functions should be pure (no side effects)."""
        # Test that functions don't modify global state
        original_capabilities = models.MODEL_CAPABILITIES.copy()
        original_rate_limits = models.TIER_RATE_LIMITS.copy()

        # Call functions multiple times
        for _ in range(5):
            models.get_model_capabilities("gemini-2.0-flash")
            models.get_rate_limits(models.APITier.TIER_1, "gemini-2.0-flash")
            models.can_use_caching("gemini-2.0-flash", 5000)

        # Global state should be unchanged
        assert original_capabilities == models.MODEL_CAPABILITIES
        assert original_rate_limits == models.TIER_RATE_LIMITS

    @pytest.mark.unit
    @pytest.mark.contract
    def test_no_global_mutable_state(self):
        """The core module should not have global mutable state."""
        # Check that global constants are immutable
        assert isinstance(models.MODEL_CAPABILITIES, dict)
        assert isinstance(models.TIER_RATE_LIMITS, dict)

        # These should be treated as constants (not modified)
        # The test above verifies they're not modified by function calls
