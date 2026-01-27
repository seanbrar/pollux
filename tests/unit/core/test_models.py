"""Contract-first unit tests for core models.

These tests verify that the model lookup functions maintain architectural
principles of determinism, explicit contracts, and pure transformations.
"""

import pytest

from pollux.core.models import (
    MODEL_CAPABILITIES,
    TIER_RATE_LIMITS,
    APITier,
    CachingCapabilities,
    ModelCapabilities,
    RateLimits,
    can_use_caching,
    get_model_capabilities,
    get_rate_limits,
)


class TestEnumCompliance:
    """Tests that verify enum types maintain type safety."""

    @pytest.mark.unit
    def test_api_tier_enum_values_are_valid(self):
        """APITier enum should have valid string values."""
        valid_tiers = ["free", "tier_1", "tier_2", "tier_3"]

        for tier in APITier:
            assert tier.value in valid_tiers

    @pytest.mark.unit
    def test_api_tier_enum_is_immutable(self):
        """APITier enum values should be immutable."""
        # Enum values should be read-only
        with pytest.raises(AttributeError):
            APITier.FREE.value = "modified"  # type: ignore


class TestDataStructureCompliance:
    """Tests that verify data structures maintain immutability and validation."""

    @pytest.mark.unit
    def test_rate_limits_constructor_is_immutable(self):
        """RateLimits should be immutable by design."""
        rate_limits = RateLimits(requests_per_minute=100, tokens_per_minute=1000)

        # Should be frozen dataclass - assignment should fail
        with pytest.raises(AttributeError):
            rate_limits.requests_per_minute = 200  # type: ignore

    @pytest.mark.unit
    def test_caching_capabilities_constructor_is_immutable(self):
        """CachingCapabilities should be immutable by design."""
        caching = CachingCapabilities(
            supports_implicit=True,
            supports_explicit=True,
            implicit_minimum_tokens=2048,
            explicit_minimum_tokens=4096,
        )

        # Should be frozen dataclass - assignment should fail
        with pytest.raises(AttributeError):
            caching.supports_implicit = False  # type: ignore

    @pytest.mark.unit
    def test_model_capabilities_constructor_is_immutable(self):
        """ModelCapabilities should be immutable by design."""
        capabilities = ModelCapabilities(
            context_window=1_000_000,
            supports_multimodal=True,
            caching=CachingCapabilities(supports_implicit=True, supports_explicit=True),
        )

        # Should be frozen dataclass - assignment should fail
        with pytest.raises(AttributeError):
            capabilities.context_window = 2_000_000  # type: ignore

    @pytest.mark.unit
    def test_data_structures_have_sensible_defaults(self):
        """Data structures should have sensible defaults for optional fields."""
        # CachingCapabilities with minimal fields
        caching = CachingCapabilities(supports_implicit=False, supports_explicit=True)
        assert caching.implicit_minimum_tokens is None
        assert caching.explicit_minimum_tokens == 4096

        # ModelCapabilities without caching
        capabilities = ModelCapabilities(
            context_window=1_000_000, supports_multimodal=True
        )
        assert capabilities.caching is None


class TestModelLookupFunctionCompliance:
    """Tests that verify model lookup functions maintain pure function principles."""

    @pytest.mark.unit
    def test_get_model_capabilities_is_deterministic(self):
        """get_model_capabilities should always return the same result for the same input."""
        model = "gemini-2.0-flash"

        # Multiple calls should return identical results
        result1 = get_model_capabilities(model)
        result2 = get_model_capabilities(model)
        result3 = get_model_capabilities(model)

        assert result1 == result2 == result3

    @pytest.mark.unit
    def test_get_model_capabilities_returns_expected_structure(self):
        """get_model_capabilities should return ModelCapabilities or None."""
        # Valid model
        capabilities = get_model_capabilities("gemini-2.0-flash")
        assert isinstance(capabilities, ModelCapabilities)
        assert capabilities.context_window == 1_000_000
        assert capabilities.supports_multimodal is True

        # Invalid model
        capabilities = get_model_capabilities("nonexistent-model")
        assert capabilities is None

    @pytest.mark.unit
    def test_get_model_capabilities_handles_all_known_models(self):
        """get_model_capabilities should handle all models in MODEL_CAPABILITIES."""
        for model_name in MODEL_CAPABILITIES:
            capabilities = get_model_capabilities(model_name)
            assert capabilities is not None
            assert isinstance(capabilities, ModelCapabilities)
            assert capabilities == MODEL_CAPABILITIES[model_name]

    @pytest.mark.unit
    def test_get_rate_limits_is_deterministic(self):
        """get_rate_limits should always return the same result for the same inputs."""
        tier = APITier.TIER_1
        model = "gemini-2.0-flash"

        # Multiple calls should return identical results
        result1 = get_rate_limits(tier, model)
        result2 = get_rate_limits(tier, model)
        result3 = get_rate_limits(tier, model)

        assert result1 == result2 == result3

    @pytest.mark.unit
    def test_get_rate_limits_returns_expected_structure(self):
        """get_rate_limits should return RateLimits or None."""
        # Valid combination
        rate_limits = get_rate_limits(APITier.TIER_1, "gemini-2.0-flash")
        assert isinstance(rate_limits, RateLimits)
        assert rate_limits.requests_per_minute == 2_000
        assert rate_limits.tokens_per_minute == 4_000_000

        # Invalid combination
        rate_limits = get_rate_limits(APITier.FREE, "nonexistent-model")
        assert rate_limits is None

    @pytest.mark.unit
    def test_get_rate_limits_handles_all_tier_model_combinations(self):
        """get_rate_limits should handle all valid tier/model combinations."""
        for tier in TIER_RATE_LIMITS:
            for model in TIER_RATE_LIMITS[tier]:
                rate_limits = get_rate_limits(tier, model)
                assert rate_limits is not None
                assert isinstance(rate_limits, RateLimits)
                assert rate_limits == TIER_RATE_LIMITS[tier][model]

    @pytest.mark.unit
    def test_can_use_caching_is_deterministic(self):
        """can_use_caching should always return the same result for the same inputs."""
        model = "gemini-2.0-flash"
        token_count = 5000

        # Multiple calls should return identical results
        result1 = can_use_caching(model, token_count)
        result2 = can_use_caching(model, token_count)
        result3 = can_use_caching(model, token_count)

        assert result1 == result2 == result3

    @pytest.mark.unit
    def test_can_use_caching_returns_expected_structure(self):
        """can_use_caching should return a dict with boolean values."""
        result = can_use_caching("gemini-2.0-flash", 5000)

        assert isinstance(result, dict)
        assert "supported" in result
        assert "implicit" in result
        assert "explicit" in result

        assert isinstance(result["supported"], bool)
        assert isinstance(result["implicit"], bool)
        assert isinstance(result["explicit"], bool)

    @pytest.mark.unit
    def test_can_use_caching_handles_unsupported_models(self):
        """can_use_caching should handle models without caching support."""
        result = can_use_caching("nonexistent-model", 5000)

        assert result == {"supported": False, "implicit": False, "explicit": False}

    @pytest.mark.unit
    def test_can_use_caching_respects_token_thresholds(self):
        """can_use_caching should respect token count thresholds."""
        model = "gemini-2.0-flash"

        # Below explicit threshold
        result_low = can_use_caching(model, 1000)
        assert result_low["explicit"] is False

        # Above explicit threshold
        result_high = can_use_caching(model, 5000)
        assert result_high["explicit"] is True

    @pytest.mark.unit
    def test_can_use_caching_handles_implicit_caching(self):
        """can_use_caching should handle models with implicit caching."""
        model = "gemini-2.5-flash-preview-05-20"

        # Below implicit threshold
        result_low = can_use_caching(model, 1000)
        assert result_low["implicit"] is False

        # Above implicit threshold
        result_high = can_use_caching(model, 3000)
        assert result_high["implicit"] is True


class TestPureFunctionCompliance:
    """Tests that verify functions maintain pure function principles."""

    @pytest.mark.unit
    def test_functions_have_no_side_effects(self):
        """Model lookup functions should have no side effects."""
        # Test that calling functions doesn't modify global state
        original_capabilities = MODEL_CAPABILITIES.copy()
        original_rate_limits = TIER_RATE_LIMITS.copy()

        # Call functions multiple times
        for _ in range(5):
            get_model_capabilities("gemini-2.0-flash")
            get_rate_limits(APITier.TIER_1, "gemini-2.0-flash")
            can_use_caching("gemini-2.0-flash", 5000)

        # Global state should be unchanged
        assert original_capabilities == MODEL_CAPABILITIES
        assert original_rate_limits == TIER_RATE_LIMITS

    @pytest.mark.unit
    def test_functions_are_referentially_transparent(self):
        """Model lookup functions should be referentially transparent."""
        model = "gemini-2.0-flash"
        tier = APITier.TIER_1
        token_count = 5000

        # Direct calls
        capabilities_direct = get_model_capabilities(model)
        rate_limits_direct = get_rate_limits(tier, model)
        caching_direct = can_use_caching(model, token_count)

        # Calls through variables
        model_var = model
        tier_var = tier
        token_var = token_count

        capabilities_var = get_model_capabilities(model_var)
        rate_limits_var = get_rate_limits(tier_var, model_var)
        caching_var = can_use_caching(model_var, token_var)

        # Results should be identical
        assert capabilities_direct == capabilities_var
        assert rate_limits_direct == rate_limits_var
        assert caching_direct == caching_var


class TestExplicitContractCompliance:
    """Tests that verify functions have explicit, clear contracts."""

    @pytest.mark.unit
    def test_get_model_capabilities_contract_is_clear(self):
        """get_model_capabilities should have a clear input/output contract."""
        import inspect

        sig = inspect.signature(get_model_capabilities)

        # Should take exactly one parameter (model)
        assert len(sig.parameters) == 1
        assert "model" in sig.parameters

        # Parameter should be typed as str
        param = sig.parameters["model"]
        assert param.annotation is str

        # Return type should be ModelCapabilities | None
        assert "ModelCapabilities" in str(sig.return_annotation)
        assert "None" in str(sig.return_annotation)

    @pytest.mark.unit
    def test_get_rate_limits_contract_is_clear(self):
        """get_rate_limits should have a clear input/output contract."""
        import inspect

        sig = inspect.signature(get_rate_limits)

        # Should take exactly two parameters (tier, model)
        assert len(sig.parameters) == 2
        assert "tier" in sig.parameters
        assert "model" in sig.parameters

        # Parameters should be properly typed
        tier_param = sig.parameters["tier"]
        model_param = sig.parameters["model"]
        assert "APITier" in str(tier_param.annotation)
        assert model_param.annotation is str

        # Return type should be RateLimits | None
        # The annotation is the resolved type, not a string
        assert "RateLimits" in str(sig.return_annotation)
        assert "None" in str(sig.return_annotation)

    @pytest.mark.unit
    def test_can_use_caching_contract_is_clear(self):
        """can_use_caching should have a clear input/output contract."""
        import inspect

        sig = inspect.signature(can_use_caching)

        # Should take exactly two parameters (model, token_count)
        assert len(sig.parameters) == 2
        assert "model" in sig.parameters
        assert "token_count" in sig.parameters

        # Parameters should be properly typed
        model_param = sig.parameters["model"]
        token_param = sig.parameters["token_count"]
        assert model_param.annotation is str
        assert token_param.annotation is int

        # Return type should be dict[str, bool]
        assert "dict" in str(sig.return_annotation)
        assert "bool" in str(sig.return_annotation)


class TestRobustnessCompliance:
    """Tests that verify functions handle edge cases robustly."""

    @pytest.mark.unit
    def test_functions_handle_empty_strings(self):
        """Functions should handle empty string inputs gracefully."""
        # Empty model name
        capabilities = get_model_capabilities("")
        assert capabilities is None

        rate_limits = get_rate_limits(APITier.FREE, "")
        assert rate_limits is None

        caching = can_use_caching("", 5000)
        assert caching == {"supported": False, "implicit": False, "explicit": False}

    @pytest.mark.unit
    def test_functions_handle_zero_token_count(self):
        """can_use_caching should handle zero token count."""
        result = can_use_caching("gemini-2.0-flash", 0)

        assert isinstance(result, dict)
        assert result["explicit"] is False  # Below threshold

    @pytest.mark.unit
    def test_functions_handle_negative_token_count(self):
        """can_use_caching should handle negative token count."""
        result = can_use_caching("gemini-2.0-flash", -1000)

        assert isinstance(result, dict)
        assert result["explicit"] is False  # Below threshold

    @pytest.mark.unit
    def test_functions_handle_very_large_token_count(self):
        """can_use_caching should handle very large token counts."""
        result = can_use_caching("gemini-2.0-flash", 1_000_000)

        assert isinstance(result, dict)
        assert result["explicit"] is True  # Above threshold

    @pytest.mark.unit
    def test_functions_handle_unicode_model_names(self):
        """Functions should handle unicode model names."""
        unicode_model = "gemini-2.0-flash-🚀"

        capabilities = get_model_capabilities(unicode_model)
        assert capabilities is None

        rate_limits = get_rate_limits(APITier.FREE, unicode_model)
        assert rate_limits is None

        caching = can_use_caching(unicode_model, 5000)
        assert caching == {"supported": False, "implicit": False, "explicit": False}
