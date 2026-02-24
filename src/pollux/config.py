"""Configuration: Frozen Config with explicit provider/model requirements."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Literal

from dotenv import load_dotenv

from pollux.errors import ConfigurationError
from pollux.retry import RetryPolicy

load_dotenv()

ProviderName = Literal["gemini", "openai"]

# Provider-specific API key environment variable names
_API_KEY_ENV_VARS: dict[ProviderName, str] = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}


@dataclass(frozen=True)
class Config:
    """Immutable configuration for Pollux execution.

    Provider and model are required—Pollux does not guess what you want.
    API keys are auto-resolved from standard environment variables.

    Example:
        config = Config(provider="gemini", model="gemini-2.0-flash")
        # API key is automatically resolved from GEMINI_API_KEY
    """

    provider: ProviderName
    model: str
    #: Auto-resolved from ``GEMINI_API_KEY`` or ``OPENAI_API_KEY`` when *None*.
    api_key: str | None = None
    use_mock: bool = False
    #: Gemini-only in v1.0; silently ignored for other providers.
    enable_caching: bool = False
    ttl_seconds: int = 3600
    request_concurrency: int = 6
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        """Auto-resolve API key and validate configuration."""
        # Validate provider
        if self.provider not in ("gemini", "openai"):
            raise ConfigurationError(
                f"Unknown provider: {self.provider!r}",
                hint="Supported providers: 'gemini', 'openai'",
            )

        # Validate numeric fields
        if self.request_concurrency < 1:
            raise ConfigurationError(
                f"request_concurrency must be ≥ 1, got {self.request_concurrency}",
                hint="This controls how many API calls run in parallel.",
            )
        if self.ttl_seconds < 0:
            raise ConfigurationError(
                f"ttl_seconds must be ≥ 0, got {self.ttl_seconds}",
                hint="This controls the cache time-to-live in seconds (0 disables caching TTL).",
            )

        # Auto-resolve API key from environment if not provided
        if self.api_key is None and not self.use_mock:
            env_var = _API_KEY_ENV_VARS[self.provider]
            resolved_key = os.environ.get(env_var)
            object.__setattr__(self, "api_key", resolved_key)

        # Validate: real API calls need a key
        if not self.use_mock and not self.api_key:
            env_var = _API_KEY_ENV_VARS[self.provider]
            raise ConfigurationError(
                f"API key required for {self.provider}",
                hint=f"Set {env_var} environment variable or pass api_key=...",
            )

    def __str__(self) -> str:
        """Return a redacted, developer-friendly representation."""
        return (
            f"Config(provider={self.provider!r}, model={self.model!r}, "
            f"api_key={'[REDACTED]' if self.api_key else None}, use_mock={self.use_mock})"
        )

    __repr__ = __str__
