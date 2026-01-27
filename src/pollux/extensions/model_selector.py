"""Auto model selector policy (advisory and optional override).

Policy:
- If total_est_tokens > 8k or heavy multimodal -> gemini-2.5-pro-preview-06-05
- Else if prompt_count >= 3 and caching enabled -> gemini-2.5-flash-preview-05-20
- Else -> fallback to configured default

Safety:
- Never override an explicitly provided model by default. The helper exposes
  a flag to allow override when the caller determines it is safe.
- Always include a structured decision payload suitable for diagnostics.

This module is pure and testable; no provider SDKs are imported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:  # typing-only import to satisfy TC003 and typing of core imports
    from collections.abc import Iterable

    from pollux.core.models import APITier, get_rate_limits

# Importing from internal core is acceptable here; still a pure function module.
if not TYPE_CHECKING:
    try:  # pragma: no cover - runtime import guard for isolated tests
        from pollux.core.models import APITier, get_rate_limits
    except Exception:  # pragma: no cover - import safety for isolated testing
        APITier = object  # type: ignore[assignment]

        def get_rate_limits(*_: object, **__: object) -> object:  # pragma: no cover
            """Stubbed `get_rate_limits` used only if core import fails during tests."""
            return None


DEFAULT_FLASH = "gemini-2.5-flash-preview-05-20"
DEFAULT_PRO = "gemini-2.5-pro-preview-06-05"

# Policy thresholds (tunable from one place)
LONG_CONTEXT_THRESHOLD_TOKENS = 8_000

# Reason codes (stabilized for analytics)
REASON_PRO_LONG_OR_MM = "pro: long_context_or_heavy_multimodal"
REASON_FLASH_VECTOR_CACHE = "flash: vectorized_with_caching"
REASON_DEFAULT_FALLBACK = "default_fallback"
REASON_REJECTED_BY_ALLOW = "rejected_by_allow_list"
REASON_REJECTED_BY_TIER = "rejected_by_tier_limits"
REASON_FALLBACK_TO_DEFAULT = "fallback_to_default"
REASON_FALLBACK_TO_CONFIGURED = "fallback_to_configured"
REASON_FALLBACK_TO_FIRST_ALLOWED = "fallback_to_first_allowed"
REASON_NO_VALID_MODEL = "no_valid_model_found"


@dataclass(frozen=True)
class SelectionInputs:
    """Inputs required to make a model selection decision."""

    total_est_tokens: int
    prompt_count: int
    caching_enabled: bool
    heavy_multimodal: bool
    configured_default: str
    configured_model: str
    # Optional hint: treat configured_model as explicitly provided by user.
    explicit_model: bool = True
    # Optional constraints
    api_tier: APITier | None = None
    allowed_models: frozenset[str] | None = None


class SelectionDecisionInputs(TypedDict):
    """Structured view of inputs included in decision payload."""

    total_est_tokens: int
    prompt_count: int
    caching_enabled: bool
    heavy_multimodal: bool
    configured_default: str
    configured_model: str
    explicit_model: bool


class SelectionDecision(TypedDict):
    """Structured selection decision suitable for JSON diagnostics."""

    selected: str
    constrained_selected: str
    inputs: SelectionDecisionInputs
    reason: list[str]
    # Optionally filled by maybe_override_model
    effective: str | None


def decide(inputs: SelectionInputs) -> SelectionDecision:
    """Return a structured selection decision without side effects.

    The return value is JSON-serializable and includes the chosen model and
    the inputs used, to support result diagnostics.
    """
    reason: list[str] = []

    # Normalize/clamp inputs to avoid pathological negatives
    total_est_tokens = max(0, int(inputs.total_est_tokens))
    prompt_count = max(0, int(inputs.prompt_count))

    # Apply policy in order (recommendation phase)
    if total_est_tokens > LONG_CONTEXT_THRESHOLD_TOKENS or inputs.heavy_multimodal:
        policy_choice = DEFAULT_PRO
        reason.append(REASON_PRO_LONG_OR_MM)
    elif prompt_count >= 3 and inputs.caching_enabled:
        policy_choice = DEFAULT_FLASH
        reason.append(REASON_FLASH_VECTOR_CACHE)
    else:
        policy_choice = inputs.configured_default
        reason.append(REASON_DEFAULT_FALLBACK)

    # Apply constraints (allow-list and tier)
    constrained = _apply_constraints(
        policy_choice,
        (
            inputs.configured_default,
            inputs.configured_model,
        ),
        allowed=inputs.allowed_models,
        tier=inputs.api_tier,
        reason=reason,
    )

    return {
        "selected": policy_choice,
        "constrained_selected": constrained,
        "inputs": {
            "total_est_tokens": total_est_tokens,
            "prompt_count": prompt_count,
            "caching_enabled": bool(inputs.caching_enabled),
            "heavy_multimodal": bool(inputs.heavy_multimodal),
            "configured_default": inputs.configured_default,
            "configured_model": inputs.configured_model,
            "explicit_model": bool(inputs.explicit_model),
        },
        "reason": reason,
        "effective": None,
    }


def _apply_constraints(
    initial: str,
    fallbacks: Iterable[str],
    *,
    allowed: frozenset[str] | None,
    tier: APITier | None,
    reason: list[str],
) -> str:
    """Return a model satisfying allow-list and tier constraints.

    Tries in order: initial, then `fallbacks` sequence. If none match, and an
    allow-list is provided, returns the first item in the allow-list. If still
    none, returns the last attempted model and records a reason.
    """

    def permitted(m: str) -> bool:
        if allowed is not None and m not in allowed:
            return False
        return not (tier is not None and get_rate_limits(tier, m) is None)

    # Helper to record why a candidate was skipped
    def record_rejection(m: str) -> None:
        if allowed is not None and m not in allowed:
            reason.append(REASON_REJECTED_BY_ALLOW)
        if tier is not None and get_rate_limits(tier, m) is None:
            reason.append(REASON_REJECTED_BY_TIER)

    # Try initial
    if permitted(initial):
        return initial
    record_rejection(initial)

    # Try fallbacks in order
    for i, fb in enumerate(fallbacks):
        if permitted(fb):
            reason.append(
                REASON_FALLBACK_TO_DEFAULT if i == 0 else REASON_FALLBACK_TO_CONFIGURED
            )
            return fb
        record_rejection(fb)

    # If allow-list exists, pick a deterministic option that satisfies tier
    if allowed:
        for m in sorted(allowed):
            if permitted(m):
                reason.append(REASON_FALLBACK_TO_FIRST_ALLOWED)
                return m

    # Nothing works: indicate this explicitly
    reason.append(REASON_NO_VALID_MODEL)
    return initial


def maybe_override_model(
    inputs: SelectionInputs, *, allow_override: bool
) -> tuple[str, SelectionDecision]:
    """Return (effective_model, decision) applying safety guarantees.

    - If ``allow_override`` is False or ``inputs.explicit_model`` is True, the
      configured model is preserved and returned, alongside the decision payload.
    - Otherwise, use the policy decision.
    """
    decision = decide(inputs)
    configured = inputs.configured_model

    if not allow_override or inputs.explicit_model:
        decision["effective"] = configured
        return configured, decision

    effective = decision.get("constrained_selected", decision["selected"])
    decision["effective"] = effective
    return effective, decision
