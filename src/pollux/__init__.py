"""Pollux: Efficient multi-prompt interactions with LLM APIs.

Public API:
    - run(): Single prompt execution
    - run_many(): Multi-prompt source-pattern execution
    - interact(): One explicit v2 interaction over an Environment and Input
    - defer(): Single deferred request submission
    - defer_many(): Multi-prompt deferred submission
    - inspect_deferred(): Inspect a deferred job
    - collect_deferred(): Collect terminal deferred results
    - cancel_deferred(): Cancel a deferred job
    - Source: Explicit input types
    - Config: Configuration dataclass
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any, cast

from pollux.config import (
    _API_KEY_ENV_VARS,
    _LOCAL_BASE_URL_ENV_VAR,
    Config,
    ProviderName,
    resolve_api_key,
)
from pollux.deferred import (
    DeferredHandle,
    DeferredSnapshot,
    cancel_deferred_handle,
    collect_deferred_handle,
    inspect_deferred_handle,
    submit_deferred,
)
from pollux.errors import (
    APIError,
    CacheError,
    ConfigurationError,
    DeferredNotReadyError,
    InternalError,
    PlanningError,
    PolluxError,
    RateLimitError,
    SourceError,
)
from pollux.interaction import (
    Continuation,
    Environment,
    Input,
    Message,
    Output,
    OutputCollection,
    OutputRequirements,
    ToolCall,
    ToolChoice,
    ToolDeclaration,
    ToolResult,
)
from pollux.interaction.execute import execute_interaction, execute_interactions
from pollux.options import Options, ResponseSchemaInput
from pollux.plan import build_plan
from pollux.providers.base import CloseableProvider
from pollux.request import normalize_request
from pollux.result import ResultEnvelope
from pollux.retry import RetryPolicy
from pollux.source import Source

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pollux.providers.base import Provider

try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("pollux-ai")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

# Library-level NullHandler: stay silent unless the consumer configures logging.
logging.getLogger("pollux").addHandler(logging.NullHandler())

logger = logging.getLogger(__name__)


def _build_requirements(
    *,
    output: ResponseSchemaInput | None,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int | None,
    seed: int | None,
    reasoning_effort: str | None,
    reasoning_budget_tokens: int | None,
    tool_choice: ToolChoice | None,
    provider_options: dict[str, dict[str, Any]] | None,
) -> OutputRequirements:
    """Assemble OutputRequirements from the friendly first-class kwargs."""
    return OutputRequirements(
        output_schema=output,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        seed=seed,
        reasoning_effort=reasoning_effort,
        reasoning_budget_tokens=reasoning_budget_tokens,
        tool_choice=tool_choice,
        provider_options=provider_options,
    )


async def run(
    prompt: str | None = None,
    *,
    source: Source | None = None,
    sources: Sequence[Source] = (),
    config: Config,
    instructions: str | None = None,
    output: ResponseSchemaInput | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    seed: int | None = None,
    reasoning_effort: str | None = None,
    reasoning_budget_tokens: int | None = None,
    tool_choice: ToolChoice | None = None,
    tools: Sequence[ToolDeclaration] | None = None,
    provider_options: dict[str, dict[str, Any]] | None = None,
) -> Output:
    """Run a single prompt, optionally with sources for context.

    The simple v2 facade: returns an :class:`Output` with named facets
    (``text``, ``structured``, ``reasoning``, ``usage``, ``metrics``, …). For
    stable environments, continuation, or tool loops, use :func:`interact`.

    Args:
        prompt: The prompt to run.
        source: A single source for context (convenience for ``sources=[source]``).
        sources: Stable sources for context.
        config: Configuration specifying provider and model.
        instructions: Optional system-level instruction.
        output: Optional Pydantic model or JSON Schema for structured output.
        temperature: Optional sampling temperature.
        top_p: Optional nucleus-sampling probability.
        max_tokens: Optional hard cap on output tokens.
        seed: Optional sampling seed where supported.
        reasoning_effort: Optional qualitative reasoning effort.
        reasoning_budget_tokens: Optional explicit reasoning token budget.
        tool_choice: Optional tool-choice control.
        tools: Optional tool declarations.
        provider_options: Optional raw provider-scoped generation options.

    Returns:
        The completed :class:`Output`.

    Example:
        config = Config(provider="anthropic", model="claude-haiku-4-5")
        result = await run("Summarize.", source=Source.from_file("doc.pdf"), config=config)
        print(result.text)
    """
    all_sources = (source,) if source is not None else tuple(sources)
    collection = await run_many(
        prompt,
        sources=all_sources,
        config=config,
        instructions=instructions,
        output=output,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        seed=seed,
        reasoning_effort=reasoning_effort,
        reasoning_budget_tokens=reasoning_budget_tokens,
        tool_choice=tool_choice,
        tools=tools,
        provider_options=provider_options,
    )
    return collection.outputs[0]


async def interact(
    environment: Environment,
    input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
    *,
    config: Config,
    output: ResponseSchemaInput | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    seed: int | None = None,
    reasoning_effort: str | None = None,
    reasoning_budget_tokens: int | None = None,
    tool_choice: ToolChoice | None = None,
    provider_options: dict[str, dict[str, Any]] | None = None,
) -> Output:
    """Run one explicit v2 interaction over an environment and input.

    The v2 interaction facade: build an :class:`Environment` once (instructions,
    sources, tools, cache preference), then send :class:`Input` turns. Returns an
    :class:`Output` with named facets (``text``, ``structured``, ``reasoning``,
    ``tool_calls``, ``continuation``, ``usage``, ``metrics``, ``diagnostics``).
    Continue by passing the prior output's ``continuation`` and any
    ``tool_results`` in the next ``Input``.

    Args:
        environment: Reusable model-facing setup for the interaction.
        input: The per-turn payload (user content, continuation, tool results).
        config: Configuration specifying provider and model.
        output: Optional Pydantic model or JSON Schema for structured output.
        temperature: Optional sampling temperature.
        top_p: Optional nucleus-sampling probability.
        max_tokens: Optional hard cap on output tokens.
        seed: Optional sampling seed where supported.
        reasoning_effort: Optional qualitative reasoning effort.
        reasoning_budget_tokens: Optional explicit reasoning token budget.
        tool_choice: Optional tool-choice control.
        provider_options: Optional raw provider-scoped generation options.

    Returns:
        The completed :class:`Output` for the interaction.

    Example:
        environment = Environment(instructions=system_prompt, tools=tool_decls)
        result = await interact(environment, Input("Inspect the repo."), config=cfg)
        while result.tool_calls:
            results = [ToolResult(call_id=c.id, content=run_tool(c)) for c in result.tool_calls]
            result = await interact(
                environment,
                Input(continuation=result.continuation, tool_results=results),
                config=cfg,
            )
    """
    requirements = _build_requirements(
        output=output,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        seed=seed,
        reasoning_effort=reasoning_effort,
        reasoning_budget_tokens=reasoning_budget_tokens,
        tool_choice=tool_choice,
        provider_options=provider_options,
    )
    provider = _get_provider(config)
    try:
        return await execute_interaction(
            environment, input, requirements, config, provider
        )
    finally:
        await _close_provider(provider)


async def defer(
    prompt: str | None = None,
    *,
    source: Source | None = None,
    config: Config,
    options: Options | None = None,
) -> DeferredHandle:
    """Submit a single deferred request and return a serializable handle."""
    sources = (source,) if source else ()
    return await defer_many(prompt, sources=sources, config=config, options=options)


async def run_many(
    prompts: str | Sequence[str | None] | None = None,
    *,
    sources: Sequence[Source] = (),
    config: Config,
    instructions: str | None = None,
    output: ResponseSchemaInput | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    seed: int | None = None,
    reasoning_effort: str | None = None,
    reasoning_budget_tokens: int | None = None,
    tool_choice: ToolChoice | None = None,
    tools: Sequence[ToolDeclaration] | None = None,
    provider_options: dict[str, dict[str, Any]] | None = None,
) -> OutputCollection:
    """Run multiple prompts with shared sources for source-pattern execution.

    Returns an :class:`OutputCollection` whose ``outputs`` preserve input order;
    ``.answers`` / ``.structured`` give ergonomic per-prompt lists.

    Args:
        prompts: One or more prompts to run.
        sources: Stable sources shared across the prompts.
        config: Configuration specifying provider and model.
        instructions: Optional system-level instruction.
        output: Optional Pydantic model or JSON Schema for structured output.
        temperature: Optional sampling temperature.
        top_p: Optional nucleus-sampling probability.
        max_tokens: Optional hard cap on output tokens.
        seed: Optional sampling seed where supported.
        reasoning_effort: Optional qualitative reasoning effort.
        reasoning_budget_tokens: Optional explicit reasoning token budget.
        tool_choice: Optional tool-choice control.
        tools: Optional tool declarations.
        provider_options: Optional raw provider-scoped generation options.

    Returns:
        The :class:`OutputCollection` for the source pattern.

    Example:
        config = Config(provider="anthropic", model="claude-haiku-4-5")
        results = await run_many(
            ["Question 1?", "Question 2?"],
            sources=[Source.from_text("Context...")],
            config=config,
        )
        for answer in results.answers:
            print(answer)
    """
    prompt_tuple = (
        (prompts,) if isinstance(prompts, (str, type(None))) else tuple(prompts)
    )
    environment = Environment(
        instructions=instructions,
        sources=tuple(sources),
        tools=tuple(tools) if tools else (),
    )
    inputs = [Input(content=prompt) for prompt in prompt_tuple]
    requirements = _build_requirements(
        output=output,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        seed=seed,
        reasoning_effort=reasoning_effort,
        reasoning_budget_tokens=reasoning_budget_tokens,
        tool_choice=tool_choice,
        provider_options=provider_options,
    )
    provider = _get_provider(config)
    try:
        return await execute_interactions(
            environment, inputs, requirements, config, provider
        )
    finally:
        await _close_provider(provider)


async def defer_many(
    prompts: str | Sequence[str | None] | None = None,
    *,
    sources: Sequence[Source] = (),
    config: Config,
    options: Options | None = None,
) -> DeferredHandle:
    """Submit deferred work and return a handle for later inspection/collection.

    Planned for Pollux 2.0: deferred submission moves to one entry point that
    can submit a single interaction or a source-pattern collection. See the
    *Migrating to 2.0* guide.
    """
    request = normalize_request(prompts, sources, config, options=options)
    if not request.prompts:
        raise ConfigurationError(
            "defer_many() requires at least one prompt",
            hint="Pass one or more prompts, or use run_many(prompts=[]) for a realtime no-op.",
        )
    plan = build_plan(request)
    provider = _get_provider(request.config)

    try:
        return await submit_deferred(plan, provider)
    finally:
        await _close_provider(provider)


async def inspect_deferred(
    handle: DeferredHandle,
) -> DeferredSnapshot:
    """Inspect the current state of a deferred job."""
    provider = _resolve_deferred_provider(handle)
    try:
        return await inspect_deferred_handle(handle, provider)
    finally:
        await _close_provider(provider)


async def collect_deferred(
    handle: DeferredHandle,
    *,
    response_schema: type[Any] | dict[str, Any] | None = None,
) -> ResultEnvelope:
    """Collect a terminal deferred job into the standard ResultEnvelope.

    Args:
        handle: The deferred handle returned by ``defer()`` / ``defer_many()``.
        response_schema: Optional Pydantic model or JSON Schema for structured
            output rehydration. Must match the schema used at submission time.
    """
    provider = _resolve_deferred_provider(handle)
    try:
        return await collect_deferred_handle(
            handle,
            provider,
            response_schema=response_schema,
        )
    finally:
        await _close_provider(provider)


async def cancel_deferred(
    handle: DeferredHandle,
) -> None:
    """Request provider-side cancellation for a deferred job."""
    provider = _resolve_deferred_provider(handle)
    try:
        await cancel_deferred_handle(handle, provider)
    finally:
        await _close_provider(provider)


async def _close_provider(provider: Provider) -> None:
    """Close provider resources without masking primary errors."""
    if isinstance(provider, CloseableProvider):
        try:
            await provider.aclose()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Provider cleanup failed: %s", exc)


@dataclass(frozen=True)
class _ProviderSpec:
    """Registry entry describing how to build and use a provider.

    ``build`` performs a lazy import so provider SDKs stay un-imported until the
    provider is actually instantiated.
    """

    build: Callable[[str | None, str | None], Provider]
    requires_api_key: bool = True
    requires_base_url: bool = False
    supports_deferred: bool = False


def _build_gemini(api_key: str | None, _base_url: str | None) -> Provider:
    from pollux.providers.gemini import GeminiProvider

    return GeminiProvider(cast("str", api_key))


def _build_openai(api_key: str | None, _base_url: str | None) -> Provider:
    from pollux.providers.openai import OpenAIProvider

    return OpenAIProvider(cast("str", api_key))


def _build_anthropic(api_key: str | None, _base_url: str | None) -> Provider:
    from pollux.providers.anthropic import AnthropicProvider

    return AnthropicProvider(cast("str", api_key))


def _build_openrouter(api_key: str | None, _base_url: str | None) -> Provider:
    from pollux.providers.openrouter import OpenRouterProvider

    return OpenRouterProvider(cast("str", api_key))


def _build_local(api_key: str | None, base_url: str | None) -> Provider:
    from pollux.providers.local import LocalProvider

    return LocalProvider(base_url=cast("str", base_url), api_key=api_key)


# Single source of truth for provider construction and lifecycle traits.
# Keep keys aligned with config.ProviderName.
_PROVIDER_REGISTRY: dict[str, _ProviderSpec] = {
    "gemini": _ProviderSpec(build=_build_gemini, supports_deferred=True),
    "openai": _ProviderSpec(build=_build_openai, supports_deferred=True),
    "anthropic": _ProviderSpec(build=_build_anthropic, supports_deferred=True),
    "openrouter": _ProviderSpec(build=_build_openrouter, supports_deferred=True),
    "local": _ProviderSpec(
        build=_build_local, requires_api_key=False, requires_base_url=True
    ),
}


def _create_provider(
    provider: str,
    api_key: str | None,
    *,
    use_mock: bool = False,
    base_url: str | None = None,
) -> Provider:
    """Instantiate a provider client from explicit parameters."""
    if use_mock:
        from pollux.providers.mock import MockProvider

        return MockProvider()

    spec = _PROVIDER_REGISTRY.get(provider)
    if spec is None:
        raise ConfigurationError(
            f"Unknown provider: {provider!r}",
            hint="Supported providers: "
            + ", ".join(repr(name) for name in _PROVIDER_REGISTRY),
        )

    if spec.requires_base_url and not base_url:
        raise ConfigurationError(
            f"base_url required for provider={provider!r}",
            hint=(
                "Pass base_url='http://localhost:...' or set "
                f"{_LOCAL_BASE_URL_ENV_VAR}."
            ),
        )
    if spec.requires_api_key and not api_key:
        env_var = _API_KEY_ENV_VARS.get(
            cast("ProviderName", provider), "the provider API key"
        )
        raise ConfigurationError(
            "api_key required for real API",
            hint=f"Set {env_var} or pass Config(api_key=...).",
        )

    return spec.build(api_key, base_url)


def _get_provider(config: Config) -> Provider:
    """Get the appropriate provider based on configuration."""
    return _create_provider(
        config.provider,
        config.api_key,
        use_mock=config.use_mock,
        base_url=config.base_url,
    )


def _resolve_deferred_provider(handle: DeferredHandle) -> Provider:
    """Resolve a provider client for deferred lifecycle calls from the handle."""
    # Gate on the registry flag, not provider.capabilities.deferred_delivery:
    # this runs before instantiation, keyed only by the persisted provider name.
    # A handle carries no base_url, so e.g. ``local`` cannot even be built to
    # inspect its capabilities. The registry flag is the pre-instantiation gate;
    # deferred.py applies the instance-level capability + protocol checks.
    spec = _PROVIDER_REGISTRY.get(handle.provider)
    if spec is None or not spec.supports_deferred:
        raise ConfigurationError(
            f"Unknown provider on deferred handle: {handle.provider!r}",
            hint="Persist Pollux DeferredHandle values without modifying their provider field.",
        )
    api_key = resolve_api_key(cast("ProviderName", handle.provider))
    return _create_provider(handle.provider, api_key)


# Re-export for convenience
__all__ = [
    "APIError",
    "CacheError",
    "Config",
    "ConfigurationError",
    "Continuation",
    "DeferredHandle",
    "DeferredNotReadyError",
    "DeferredSnapshot",
    "Environment",
    "Input",
    "InternalError",
    "Message",
    "Options",
    "Output",
    "OutputCollection",
    "OutputRequirements",
    "PlanningError",
    "PolluxError",
    "RateLimitError",
    "ResultEnvelope",
    "RetryPolicy",
    "Source",
    "SourceError",
    "ToolCall",
    "ToolChoice",
    "ToolDeclaration",
    "ToolResult",
    "cancel_deferred",
    "collect_deferred",
    "defer",
    "defer_many",
    "inspect_deferred",
    "interact",
    "run",
    "run_many",
]
