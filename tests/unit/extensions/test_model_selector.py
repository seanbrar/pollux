from __future__ import annotations

from pollux.core.models import APITier
from pollux.extensions.model_selector import (
    SelectionInputs,
    decide,
    maybe_override_model,
)


def test_model_selector_prefers_pro_for_long_context():
    inp = SelectionInputs(
        total_est_tokens=9001,
        prompt_count=1,
        caching_enabled=False,
        heavy_multimodal=False,
        configured_default="gemini-2.5-flash-preview-05-20",
        configured_model="gemini-2.5-flash-preview-05-20",
        explicit_model=False,
    )
    d = decide(inp)
    assert d["selected"].endswith("pro-preview-06-05")


def test_model_selector_prefers_flash_for_vectorized_with_caching():
    inp = SelectionInputs(
        total_est_tokens=500,
        prompt_count=3,
        caching_enabled=True,
        heavy_multimodal=False,
        configured_default="gemini-2.0-flash",
        configured_model="gemini-2.0-flash",
        explicit_model=False,
    )
    d = decide(inp)
    assert d["selected"].endswith("flash-preview-05-20")


def test_maybe_override_respects_explicit():
    inp = SelectionInputs(
        total_est_tokens=12000,
        prompt_count=2,
        caching_enabled=False,
        heavy_multimodal=False,
        configured_default="gemini-2.0-flash",
        configured_model="gemini-2.5-flash-preview-05-20",
        explicit_model=True,
    )
    model, decision = maybe_override_model(inp, allow_override=True)
    # remains as configured
    assert model == inp.configured_model
    assert decision["selected"].endswith("pro-preview-06-05")


def test_model_selector_prefers_pro_for_heavy_multimodal():
    inp = SelectionInputs(
        total_est_tokens=100,
        prompt_count=1,
        caching_enabled=False,
        heavy_multimodal=True,
        configured_default="gemini-2.5-flash-preview-05-20",
        configured_model="gemini-2.5-flash-preview-05-20",
        explicit_model=False,
    )
    d = decide(inp)
    assert d["selected"].endswith("pro-preview-06-05")


def test_model_selector_default_fallback_branch():
    inp = SelectionInputs(
        total_est_tokens=100,
        prompt_count=1,
        caching_enabled=False,
        heavy_multimodal=False,
        configured_default="gemini-2.0-flash",
        configured_model="gemini-2.0-flash",
        explicit_model=False,
    )
    d = decide(inp)
    assert d["selected"] == "gemini-2.0-flash"


def test_model_selector_normalizes_negative_inputs():
    inp = SelectionInputs(
        total_est_tokens=-10,
        prompt_count=-2,
        caching_enabled=False,
        heavy_multimodal=False,
        configured_default="gemini-2.0-flash",
        configured_model="gemini-2.0-flash",
        explicit_model=False,
    )
    d = decide(inp)
    assert d["selected"] == "gemini-2.0-flash"
    assert d["inputs"]["total_est_tokens"] == 0
    assert d["inputs"]["prompt_count"] == 0


def test_model_selector_enforces_tier_constraints_with_fallback():
    # Policy would choose PRO, but FREE tier disallows it; fallback to default FLASH preview
    inp = SelectionInputs(
        total_est_tokens=20_000,
        prompt_count=1,
        caching_enabled=False,
        heavy_multimodal=False,
        configured_default="gemini-2.5-flash-preview-05-20",
        configured_model="gemini-2.5-flash-preview-05-20",
        explicit_model=False,
        api_tier=APITier.FREE,
    )
    d = decide(inp)
    assert d["selected"].endswith("pro-preview-06-05")  # policy pick
    # Constrained by FREE tier, should fall back to default flash preview
    assert d["constrained_selected"] == "gemini-2.5-flash-preview-05-20"


def test_model_selector_enforces_allow_list_constraints():
    # Vectorized+caching suggests flash preview, but allow-list restricts to 2.0-flash
    allowed = frozenset({"gemini-2.0-flash"})
    inp = SelectionInputs(
        total_est_tokens=100,
        prompt_count=3,
        caching_enabled=True,
        heavy_multimodal=False,
        configured_default="gemini-2.0-flash",
        configured_model="gemini-2.0-flash",
        explicit_model=False,
        allowed_models=allowed,
    )
    d = decide(inp)
    assert d["selected"].endswith("flash-preview-05-20")  # policy pick
    assert d["constrained_selected"] == "gemini-2.0-flash"


def test_maybe_override_populates_effective_field():
    # With allow_override=False, effective is configured_model
    inp = SelectionInputs(
        total_est_tokens=20_000,
        prompt_count=1,
        caching_enabled=False,
        heavy_multimodal=False,
        configured_default="gemini-2.5-flash-preview-05-20",
        configured_model="gemini-2.5-flash-preview-05-20",
        explicit_model=False,
        api_tier=APITier.TIER_1,
    )
    model, decision = maybe_override_model(inp, allow_override=False)
    assert model == inp.configured_model
    assert decision["effective"] == inp.configured_model

    # With allow_override=True and not explicit, effective follows constrained selection
    model2, decision2 = maybe_override_model(inp, allow_override=True)
    assert model2 == decision2["constrained_selected"]
    assert decision2["effective"] == model2
