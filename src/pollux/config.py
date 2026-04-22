"""Configuration: Frozen Config with explicit provider/model requirements."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Literal, get_args

import dotenv

from pollux.errors import ConfigurationError
from pollux.retry import RetryPolicy

ProviderName = Literal["gemini", "openai", "anthropic", "openrouter", "local"]

# Provider-specific API key environment variable names.
# "local" is intentionally absent — self-hosted servers do not require a key.
_API_KEY_ENV_VARS: dict[ProviderName, str] = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

_LOCAL_BASE_URL_ENV_VAR = "POLLUX_LOCAL_BASE_URL"

_SUPPORTED_PROVIDERS = get_args(ProviderName)


def resolve_api_key(provider: ProviderName) -> str | None:
    """Resolve an API key for *provider* using env vars and lazy dotenv loading."""
    env_var = _API_KEY_ENV_VARS.get(provider)
    if env_var is None:
        return None
    resolved_key = os.environ.get(env_var)
    if not resolved_key:
        dotenv.load_dotenv()
        resolved_key = os.environ.get(env_var)
    return resolved_key


def _resolve_local_base_url() -> str | None:
    """Resolve POLLUX_LOCAL_BASE_URL with lazy dotenv loading."""
    resolved = os.environ.get(_LOCAL_BASE_URL_ENV_VAR)
    if not resolved:
        dotenv.load_dotenv()
        resolved = os.environ.get(_LOCAL_BASE_URL_ENV_VAR)
    return resolved


@dataclass(frozen=True)
class Config:
    """Immutable configuration for Pollux execution.

    Provider and model are required—Pollux does not guess what you want.
    API keys are auto-resolved from standard environment variables.

    Example:
        config = Config(provider="gemini", model="gemini-2.0-flash")
        # API key is automatically resolved from GEMINI_API_KEY

    For self-hosted OpenAI-compatible servers, use ``provider="local"`` with
    a ``base_url`` (or set ``POLLUX_LOCAL_BASE_URL``). No API key is required.
    """

    provider: ProviderName
    model: str
    #: Auto-resolved from the provider-specific API key env var when *None*.
    #: Optional for ``provider="local"``.
    api_key: str | None = None
    #: Required for ``provider="local"``; rejected for cloud providers.
    #: Falls back to ``POLLUX_LOCAL_BASE_URL`` when unset.
    base_url: str | None = None
    use_mock: bool = False
    request_concurrency: int = 6
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        """Auto-resolve credentials and validate configuration."""
        # Validate provider
        if self.provider not in _SUPPORTED_PROVIDERS:
            raise ConfigurationError(
                f"Unknown provider: {self.provider!r}",
                hint=(
                    "Supported providers: "
                    + ", ".join(repr(p) for p in _SUPPORTED_PROVIDERS)
                ),
            )

        # Validate numeric fields
        if not isinstance(self.request_concurrency, int):
            raise ConfigurationError(
                f"request_concurrency must be an integer, got {type(self.request_concurrency).__name__}",
                hint="Pass a whole number ≥ 1 for request_concurrency.",
            )
        if self.request_concurrency < 1:
            raise ConfigurationError(
                f"request_concurrency must be ≥ 1, got {self.request_concurrency}",
                hint="This controls how many API calls run in parallel.",
            )

        if self.provider == "local":
            # Local: resolve base_url for real calls, skip API-key resolution entirely.
            if self.base_url is None and not self.use_mock:
                env_url = _resolve_local_base_url()
                if env_url:
                    object.__setattr__(self, "base_url", env_url)
            if not self.use_mock and not self.base_url:
                raise ConfigurationError(
                    "base_url required for provider='local'",
                    hint=(
                        "Pass base_url='http://localhost:...' or set "
                        f"{_LOCAL_BASE_URL_ENV_VAR}."
                    ),
                )
            return

        # Cloud providers: base_url is not a meaningful override here.
        if self.base_url is not None:
            raise ConfigurationError(
                f"base_url is only valid for provider='local', not {self.provider!r}",
                hint="Remove base_url, or switch to provider='local'.",
            )

        # Auto-resolve API key from environment if not provided
        if self.api_key is None and not self.use_mock:
            object.__setattr__(self, "api_key", resolve_api_key(self.provider))

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
            f"api_key={'[REDACTED]' if self.api_key else None}, "
            f"base_url={self.base_url!r}, use_mock={self.use_mock})"
        )

    __repr__ = __str__
