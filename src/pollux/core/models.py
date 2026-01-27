"""Model capabilities and tier information."""

from dataclasses import dataclass
from enum import Enum


class APITier(Enum):
    """API billing tier."""

    FREE = "free"
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


@dataclass(frozen=True)
class RateLimits:
    """Rate limit configuration."""

    requests_per_minute: int
    tokens_per_minute: int


@dataclass(frozen=True)
class CachingCapabilities:
    """Caching capability information."""

    supports_implicit: bool
    supports_explicit: bool
    implicit_minimum_tokens: int | None = None
    explicit_minimum_tokens: int = 4096


@dataclass(frozen=True)
class ModelCapabilities:
    """Complete model capability information."""

    context_window: int
    supports_multimodal: bool
    caching: CachingCapabilities | None = None


# Pure data - no complex classes
MODEL_CAPABILITIES: dict[str, ModelCapabilities] = {
    "gemini-2.5-flash-preview-05-20": ModelCapabilities(
        context_window=1_000_000,
        supports_multimodal=True,
        caching=CachingCapabilities(
            supports_implicit=True,
            supports_explicit=True,
            implicit_minimum_tokens=2048,
            explicit_minimum_tokens=4096,
        ),
    ),
    "gemini-2.5-pro-preview-06-05": ModelCapabilities(
        context_window=2_000_000,
        supports_multimodal=True,
        caching=CachingCapabilities(
            supports_implicit=True,
            supports_explicit=True,
            implicit_minimum_tokens=2048,
            explicit_minimum_tokens=4096,
        ),
    ),
    "gemini-2.0-flash": ModelCapabilities(
        context_window=1_000_000,
        supports_multimodal=True,
        caching=CachingCapabilities(
            supports_implicit=False,
            supports_explicit=True,
            explicit_minimum_tokens=4096,
        ),
    ),
    "gemini-2.0-flash-lite": ModelCapabilities(
        context_window=1_000_000,
        supports_multimodal=True,
        caching=CachingCapabilities(
            supports_implicit=False,
            supports_explicit=True,
            explicit_minimum_tokens=4096,
        ),
    ),
    "gemini-1.5-flash": ModelCapabilities(
        context_window=1_000_000,
        supports_multimodal=True,
        caching=CachingCapabilities(
            supports_implicit=False,
            supports_explicit=True,
            explicit_minimum_tokens=4096,
        ),
    ),
    "gemini-1.5-flash-8b": ModelCapabilities(
        context_window=1_000_000,
        supports_multimodal=True,
        caching=CachingCapabilities(
            supports_implicit=False,
            supports_explicit=True,
            explicit_minimum_tokens=4096,
        ),
    ),
    "gemini-1.5-pro": ModelCapabilities(
        context_window=2_000_000,
        supports_multimodal=True,
        caching=CachingCapabilities(
            supports_implicit=False,
            supports_explicit=True,
            explicit_minimum_tokens=4096,
        ),
    ),
}

TIER_RATE_LIMITS: dict[APITier, dict[str, RateLimits]] = {
    APITier.FREE: {
        "gemini-2.5-flash-preview-05-20": RateLimits(10, 250_000),
        "gemini-2.0-flash": RateLimits(15, 1_000_000),
        "gemini-2.0-flash-lite": RateLimits(30, 1_000_000),
        "gemini-1.5-flash": RateLimits(15, 250_000),
        "gemini-1.5-flash-8b": RateLimits(15, 250_000),
    },
    APITier.TIER_1: {
        "gemini-2.5-flash-preview-05-20": RateLimits(1_000, 1_000_000),
        "gemini-2.5-pro-preview-06-05": RateLimits(150, 2_000_000),
        "gemini-2.0-flash": RateLimits(2_000, 4_000_000),
        "gemini-2.0-flash-lite": RateLimits(4_000, 4_000_000),
        "gemini-1.5-flash": RateLimits(2_000, 4_000_000),
        "gemini-1.5-flash-8b": RateLimits(4_000, 4_000_000),
        "gemini-1.5-pro": RateLimits(1_000, 4_000_000),
    },
    APITier.TIER_2: {
        "gemini-2.5-flash-preview-05-20": RateLimits(2_000, 3_000_000),
        "gemini-2.5-pro-preview-06-05": RateLimits(1_000, 5_000_000),
        "gemini-2.0-flash": RateLimits(10_000, 10_000_000),
        "gemini-2.0-flash-lite": RateLimits(20_000, 10_000_000),
        "gemini-1.5-flash": RateLimits(2_000, 4_000_000),
        "gemini-1.5-flash-8b": RateLimits(4_000, 4_000_000),
        "gemini-1.5-pro": RateLimits(1_000, 4_000_000),
    },
    APITier.TIER_3: {
        "gemini-2.5-flash-preview-05-20": RateLimits(10_000, 8_000_000),
        "gemini-2.5-pro-preview-06-05": RateLimits(2_000, 8_000_000),
        "gemini-2.0-flash": RateLimits(30_000, 30_000_000),
        "gemini-2.0-flash-lite": RateLimits(30_000, 30_000_000),
    },
}


# Pure functions instead of methods
def get_model_capabilities(model: str) -> ModelCapabilities | None:
    """Get capabilities for a model."""
    return MODEL_CAPABILITIES.get(model)


def get_rate_limits(tier: APITier, model: str) -> RateLimits | None:
    """Get rate limits for a tier/model combination."""
    return TIER_RATE_LIMITS.get(tier, {}).get(model)


def can_use_caching(model: str, token_count: int) -> dict[str, bool]:
    """Determine if caching can be used for a model/content combination."""
    capabilities = get_model_capabilities(model)
    if not capabilities or not capabilities.caching:
        return {"supported": False, "implicit": False, "explicit": False}

    caching = capabilities.caching
    return {
        "supported": True,
        "implicit": caching.supports_implicit
        and token_count >= (caching.implicit_minimum_tokens or float("inf")),
        "explicit": caching.supports_explicit
        and token_count >= caching.explicit_minimum_tokens,
    }
