"""Pollux: Efficient multi-prompt interactions with LLM APIs.

Public API:
    - run(): Single prompt execution
    - run_many(): Multi-prompt source-pattern execution
    - Source: Explicit input types
    - Config: Configuration dataclass
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from pollux.cache import CacheRegistry
from pollux.config import Config
from pollux.errors import (
    APIError,
    CacheError,
    ConfigurationError,
    InternalError,
    PlanningError,
    PolluxError,
    RateLimitError,
    SourceError,
)
from pollux.execute import execute_plan
from pollux.options import Options
from pollux.plan import build_plan
from pollux.request import normalize_request
from pollux.result import ResultEnvelope, build_result
from pollux.retry import RetryPolicy
from pollux.source import Source

if TYPE_CHECKING:
    from pollux.providers.base import Provider

try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("pollux-ai")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

# Library-level NullHandler: stay silent unless the consumer configures logging.
logging.getLogger("pollux").addHandler(logging.NullHandler())

logger = logging.getLogger(__name__)

# Module-level cache registry for reuse across calls
_registry = CacheRegistry()


async def run(
    prompt: str | None = None,
    *,
    source: Source | None = None,
    config: Config,
    options: Options | None = None,
) -> ResultEnvelope:
    """Run a single prompt, optionally with a source for context.

    Args:
        prompt: The prompt to run.
        source: Optional source for context (file, text, URL).
        config: Configuration specifying provider and model.
        options: Optional additive features (schema, reasoning, delivery mode).

    Returns:
        ResultEnvelope with answers and metrics.

    Example:
        config = Config(provider="gemini", model="gemini-2.0-flash")
        result = await run("Summarize this document", source=Source.from_file("doc.pdf"), config=config)
        first_answer = next(iter(result["answers"]), "")
        print(first_answer)
    """
    sources = (source,) if source else ()
    return await run_many(prompt, sources=sources, config=config, options=options)


async def run_many(
    prompts: str | list[str | None] | tuple[str | None, ...] | None = None,
    *,
    sources: tuple[Source, ...] | list[Source] = (),
    config: Config,
    options: Options | None = None,
) -> ResultEnvelope:
    """Run multiple prompts with shared sources for source-pattern execution.

    Args:
        prompts: One or more prompts to run.
        sources: Optional sources for shared context.
        config: Configuration specifying provider and model.
        options: Optional additive features (schema, reasoning, delivery mode).

    Returns:
        ResultEnvelope with answers (one per prompt) and metrics.

    Example:
        config = Config(provider="gemini", model="gemini-2.0-flash")
        result = await run_many(
            ["Question 1?", "Question 2?"],
            sources=[Source.from_text("Context...")],
            config=config,
        )
        for answer in result["answers"]:
            print(answer)
    """
    request = normalize_request(prompts, sources, config, options=options)
    plan = build_plan(request)
    provider = _get_provider(request.config)

    try:
        trace = await execute_plan(plan, provider, _registry)
    finally:
        aclose = getattr(provider, "aclose", None)
        if callable(aclose):
            try:
                await aclose()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Cleanup should never mask the primary failure.
                logger.warning("Provider cleanup failed: %s", exc)

    return build_result(plan, trace)


async def continue_tool(
    continue_from: ResultEnvelope,
    tool_results: list[dict[str, Any]],
    *,
    config: Config,
    options: Options | None = None,
) -> ResultEnvelope:
    """Continue a conversation with the results of tool calls.

    Args:
        continue_from: The previous ResultEnvelope containing tool calls.
        tool_results: List of tool results as dicts (must provide 'role': 'tool',
            'tool_call_id', and 'content').
        config: Configuration specifying provider and model.
        options: Optional additive features.

    Returns:
        ResultEnvelope with the model's next response.
    """
    import copy

    new_state = copy.deepcopy(continue_from.get("_conversation_state", {}))
    new_state["history"] = new_state.get("history", []) + tool_results

    # Build a synthetic envelope to carry the updated state and response_id
    synthetic_envelope: ResultEnvelope = {"_conversation_state": new_state}

    # Merge options, favoring the synthetic continue_from
    # Do not mutate the caller's options object
    if options is None:
        merged_options = Options(continue_from=synthetic_envelope)
    else:
        # copy dict and strip conflicting fields
        kwargs = dict(options.__dict__)
        kwargs.pop("history", None)
        kwargs.pop("continue_from", None)
        merged_options = Options(continue_from=synthetic_envelope, **kwargs)

    return await run(prompt=None, config=config, options=merged_options)


def _get_provider(config: Config) -> Provider:
    """Get the appropriate provider based on configuration."""
    if config.use_mock:
        from pollux.providers.mock import MockProvider

        return MockProvider()

    if config.provider == "openai":
        from pollux.providers.openai import OpenAIProvider

        if not config.api_key:
            raise ConfigurationError(
                "api_key required for real API",
                hint="Set OPENAI_API_KEY or pass Config(api_key=...).",
            )
        return OpenAIProvider(config.api_key)

    if config.provider == "anthropic":
        from pollux.providers.anthropic import AnthropicProvider

        if not config.api_key:
            raise ConfigurationError(
                "api_key required for real API",
                hint="Set ANTHROPIC_API_KEY or pass Config(api_key=...).",
            )
        return AnthropicProvider(config.api_key)

    from pollux.providers.gemini import GeminiProvider

    if not config.api_key:
        raise ConfigurationError(
            "api_key required for real API",
            hint="Set GEMINI_API_KEY or pass Config(api_key=...).",
        )
    return GeminiProvider(config.api_key)


# Re-export for convenience
__all__ = [
    "APIError",
    "CacheError",
    "Config",
    "ConfigurationError",
    "InternalError",
    "Options",
    "PlanningError",
    "PolluxError",
    "RateLimitError",
    "ResultEnvelope",
    "RetryPolicy",
    "Source",
    "SourceError",
    "continue_tool",
    "run",
    "run_many",
]
