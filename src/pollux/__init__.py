"""Pollux: Efficient multi-prompt interactions with LLM APIs.

Public API:
    - run(): Single prompt execution
    - run_many(): Multi-prompt source-pattern execution
    - interact(): One explicit v2 interaction over an Environment and Input
    - prepare_environment(): Build a reusable Environment, front-loading cache I/O
    - defer(): Deferred submission of one or more interactions
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
    ContextOverflowError,
    DeferredNotReadyError,
    InternalError,
    PlanningError,
    PolluxError,
    RateLimitError,
    SourceError,
    ToolCallParseError,
)
from pollux.interaction import (
    CachePolicy,
    CacheSetting,
    Continuation,
    Environment,
    EnvironmentSnapshot,
    Event,
    Input,
    Message,
    Output,
    OutputCollection,
    OutputRequirements,
    ToolCall,
    ToolCallDelta,
    ToolChoice,
    ToolDeclaration,
    ToolResult,
)
from pollux.interaction.execute import (
    execute_interaction,
    execute_interactions,
    resolve_persistent_cache,
    stream_interaction,
)
from pollux.providers.base import (
    CloseableProvider,
    ProviderReadiness,
    ReadinessProvider,
)
from pollux.retry import RetryPolicy
from pollux.source import Source

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence

    from pollux.interaction.schema import ResponseSchemaInput
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
    environment: Environment | None = None,
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
        environment: Optional prepared :class:`Environment` (e.g. from
            :func:`prepare_environment`) carrying instructions, sources, tools,
            and cache preference. Cannot be combined with inline
            ``instructions``/``source``/``sources``/``tools``.
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
    if environment is not None and source is not None:
        raise ConfigurationError(
            "environment cannot be combined with inline source/sources",
            hint="Build the Environment with the sources, or drop the environment.",
        )
    all_sources = (source,) if source is not None else tuple(sources)
    collection = await run_many(
        prompt,
        sources=all_sources,
        config=config,
        environment=environment,
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
    async with Session(config) as session:
        return await session.interact(
            environment,
            input,
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


async def stream(
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
) -> AsyncIterator[Event]:
    """Stream one explicit v2 interaction as :class:`Event` objects.

    The streaming sibling of :func:`interact`: same environment/input/config and
    the same completed result, observed as a timeline. Iterate the events
    (``text_delta``, ``reasoning_delta``, ``tool_call_delta``, ``tool_call``,
    ``usage``, ``finish``) and read the final assembled :class:`Output` from the
    terminal ``done`` event, whose ``output`` matches what :func:`interact` would
    return for the same interaction. Consumers never parse SSE or provider chunks.

    A provider that does not support streaming raises ``ConfigurationError``. A
    mid-stream provider failure raises from the iterator rather than emitting a
    ``done`` event, so a failed interaction never yields a final output.

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

    Yields:
        Each :class:`Event` in the interaction's timeline, ending in ``done``.

    Example:
        async for event in stream(environment, Input("Inspect the repo."), config=cfg):
            if event.type == "text_delta":
                print(event.text, end="")
            elif event.type == "done":
                result = event.output
    """
    async with Session(config) as session:
        async for event in session.stream(
            environment,
            input,
            output=output,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            seed=seed,
            reasoning_effort=reasoning_effort,
            reasoning_budget_tokens=reasoning_budget_tokens,
            tool_choice=tool_choice,
            provider_options=provider_options,
        ):
            yield event


class Session:
    """Reusable Pollux runtime for multi-turn agent loops.

    The one-shot helpers create and close a provider per call. ``Session`` owns a
    single provider instance so clients with many sequential turns can reuse
    transport resources while still going through the public interaction APIs.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._provider = _get_provider(config)
        self._closed = False

    async def __aenter__(self) -> Session:  # noqa: PYI034
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: object,
    ) -> None:
        """Close provider resources when leaving the async context manager."""
        await self.aclose()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ConfigurationError(
                "Pollux Session is closed",
                hint="Create a new Session for additional interactions.",
            )

    async def interact(
        self,
        environment: Environment,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        *,
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
        """Run one interaction using the session's provider instance."""
        self._ensure_open()
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
        return await execute_interaction(
            environment, input, requirements, self.config, self._provider
        )

    async def stream(
        self,
        environment: Environment,
        input: Input,  # noqa: A002 - "input" is the canonical v2 primitive name
        *,
        output: ResponseSchemaInput | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        seed: int | None = None,
        reasoning_effort: str | None = None,
        reasoning_budget_tokens: int | None = None,
        tool_choice: ToolChoice | None = None,
        provider_options: dict[str, dict[str, Any]] | None = None,
    ) -> AsyncIterator[Event]:
        """Stream one interaction using the session's provider instance."""
        self._ensure_open()
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
        async for event in stream_interaction(
            environment, input, requirements, self.config, self._provider
        ):
            yield event

    async def run_many(
        self,
        prompts: str | Sequence[str | None] | None = None,
        *,
        sources: Sequence[Source] = (),
        environment: Environment | None = None,
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
        """Run source-pattern prompts using the session's provider instance."""
        self._ensure_open()
        prompt_tuple = (
            (prompts,) if isinstance(prompts, (str, type(None))) else tuple(prompts)
        )
        if environment is not None:
            if sources or instructions is not None or tools is not None:
                raise ConfigurationError(
                    "environment cannot be combined with inline instructions/sources/tools",
                    hint="Put instructions, sources, and tools on the Environment, "
                    "or drop the environment argument.",
                )
            resolved_environment = environment
        else:
            resolved_environment = Environment(
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
        return await execute_interactions(
            resolved_environment, inputs, requirements, self.config, self._provider
        )

    async def check_ready(self) -> ProviderReadiness:
        """Return provider readiness for this session's config."""
        self._ensure_open()
        if isinstance(self._provider, ReadinessProvider):
            return await self._provider.check_ready(model=self.config.model)
        return ProviderReadiness(
            ready=True,
            provider=self.config.provider,
            model=self.config.model,
            message="Provider has no explicit readiness probe.",
            model_verified=False,
        )

    async def aclose(self) -> None:
        """Close the session's provider resources."""
        if self._closed:
            return
        self._closed = True
        await _close_provider(self._provider)


async def check_ready(config: Config) -> ProviderReadiness:
    """Run a fast provider readiness probe and close provider resources."""
    provider = _get_provider(config)
    try:
        if isinstance(provider, ReadinessProvider):
            return await provider.check_ready(model=config.model)
        return ProviderReadiness(
            ready=True,
            provider=config.provider,
            model=config.model,
            message="Provider has no explicit readiness probe.",
            model_verified=False,
        )
    finally:
        await _close_provider(provider)


def local_reasoning(*, enabled: bool = False) -> dict[str, dict[str, Any]]:
    """Return local provider options for servers with ``enable_thinking`` support."""
    return {"local": {"chat_template_kwargs": {"enable_thinking": enabled}}}


async def defer(
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
    provider_options: dict[str, dict[str, Any]] | None = None,
) -> DeferredHandle:
    """Submit one or more deferred requests and return a serializable handle.

    The v2 deferred frontdoor: submit a single interaction or a source-pattern
    collection on a provider-side timeline, then :func:`inspect_deferred` and
    :func:`collect_deferred` later. Collection returns an
    :class:`OutputCollection`, the same shape as :func:`run_many`.

    Tool calling, continuation, and persistent caching are out of scope for
    deferred delivery and are intentionally not part of this surface.

    Args:
        prompts: One or more prompts to submit.
        sources: Stable sources shared across the prompts.
        config: Configuration specifying provider and model.
        instructions: Optional system-level instruction.
        output: Optional Pydantic model or JSON Schema for structured output.
            Pass the same schema to :func:`collect_deferred` to rehydrate.
        temperature: Optional sampling temperature.
        top_p: Optional nucleus-sampling probability.
        max_tokens: Optional hard cap on output tokens.
        seed: Optional sampling seed where supported.
        reasoning_effort: Optional qualitative reasoning effort.
        reasoning_budget_tokens: Optional explicit reasoning token budget.
        provider_options: Optional raw provider-scoped generation options.

    Returns:
        A serializable :class:`DeferredHandle` for the submitted job.
    """
    prompt_tuple = (
        (prompts,) if isinstance(prompts, (str, type(None))) else tuple(prompts)
    )
    if not prompt_tuple:
        raise ConfigurationError(
            "defer() requires at least one prompt",
            hint="Pass one or more prompts to submit for deferred collection.",
        )
    environment = Environment(instructions=instructions, sources=tuple(sources))
    inputs = [Input(content=prompt) for prompt in prompt_tuple]
    requirements = _build_requirements(
        output=output,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        seed=seed,
        reasoning_effort=reasoning_effort,
        reasoning_budget_tokens=reasoning_budget_tokens,
        tool_choice=None,
        provider_options=provider_options,
    )
    provider = _get_provider(config)
    try:
        return await submit_deferred(
            environment, inputs, requirements, config, provider
        )
    finally:
        await _close_provider(provider)


async def run_many(
    prompts: str | Sequence[str | None] | None = None,
    *,
    sources: Sequence[Source] = (),
    config: Config,
    environment: Environment | None = None,
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
        environment: Optional prepared :class:`Environment` (e.g. from
            :func:`prepare_environment`) carrying instructions, sources, tools,
            and cache preference. Cannot be combined with inline
            ``instructions``/``sources``/``tools``.
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
    async with Session(config) as session:
        return await session.run_many(
            prompts,
            sources=sources,
            environment=environment,
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


async def prepare_environment(
    *,
    sources: Sequence[Source] = (),
    config: Config,
    instructions: str | None = None,
    tools: Sequence[ToolDeclaration] | None = None,
    cache: CacheSetting = None,
    metadata: dict[str, Any] | None = None,
) -> Environment:
    """Prepare a reusable :class:`Environment`, front-loading cache/upload I/O.

    Build the stable model-facing setup once and reuse it across
    :func:`interact`, :func:`run`, and :func:`run_many` calls. When ``cache`` is
    a :class:`CachePolicy`, the persistent cache is created now (uploading
    sources and surfacing capability errors early); later interactions over the
    returned environment reuse it by identity.

    Args:
        sources: Stable sources to bake into the environment (and its cache).
        config: Configuration specifying provider and model.
        instructions: Optional system-level instruction.
        tools: Optional tool declarations.
        cache: Cache preference: a :class:`CachePolicy` for persistent caching,
            ``"auto"`` for provider-managed caching, ``"none"`` to disable, or
            ``None`` for the default.
        metadata: Optional provider-neutral metadata for planning.

    Returns:
        The prepared :class:`Environment`.

    Example:
        environment = await prepare_environment(
            sources=[Source.from_file("paper.pdf")],
            instructions=system_prompt,
            cache=CachePolicy(ttl_seconds=3600),
            config=config,
        )
        results = await run_many(prompts, environment=environment, config=config)
    """
    environment = Environment(
        instructions=instructions,
        sources=tuple(sources),
        tools=tuple(tools) if tools else (),
        cache=cache,
        metadata=metadata,
    )
    if isinstance(cache, CachePolicy):
        provider = _get_provider(config)
        try:
            snapshot = EnvironmentSnapshot.from_environment(
                environment, provider=config.provider
            )
            await resolve_persistent_cache(snapshot, config, provider)
        finally:
            await _close_provider(provider)
    return environment


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
) -> OutputCollection:
    """Collect a terminal deferred job into an :class:`OutputCollection`.

    Returns the same shape as :func:`run_many`: one :class:`Output` per
    submitted request, in submission order. Each output's
    ``diagnostics.raw["deferred"]`` carries the job id and per-item status.

    Args:
        handle: The deferred handle returned by :func:`defer`.
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
    return _build_local_with_timeout(api_key, base_url, 300.0)


def _build_local_with_timeout(
    api_key: str | None,
    base_url: str | None,
    request_timeout_s: float,
) -> Provider:
    from pollux.providers.local import LocalProvider

    return LocalProvider(
        base_url=cast("str", base_url),
        api_key=api_key,
        timeout_s=request_timeout_s,
    )


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
    request_timeout_s: float = 300.0,
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

    if provider == "local":
        return _build_local_with_timeout(
            api_key,
            base_url,
            request_timeout_s,
        )
    return spec.build(api_key, base_url)


def _get_provider(config: Config) -> Provider:
    """Get the appropriate provider based on configuration."""
    return _create_provider(
        config.provider,
        config.api_key,
        use_mock=config.use_mock,
        base_url=config.base_url,
        request_timeout_s=config.request_timeout_s,
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
    "CachePolicy",
    "CacheSetting",
    "Config",
    "ConfigurationError",
    "ContextOverflowError",
    "Continuation",
    "DeferredHandle",
    "DeferredNotReadyError",
    "DeferredSnapshot",
    "Environment",
    "Event",
    "Input",
    "InternalError",
    "Message",
    "Output",
    "OutputCollection",
    "OutputRequirements",
    "PlanningError",
    "PolluxError",
    "ProviderReadiness",
    "RateLimitError",
    "RetryPolicy",
    "Session",
    "Source",
    "SourceError",
    "ToolCall",
    "ToolCallDelta",
    "ToolCallParseError",
    "ToolChoice",
    "ToolDeclaration",
    "ToolResult",
    "cancel_deferred",
    "check_ready",
    "collect_deferred",
    "defer",
    "inspect_deferred",
    "interact",
    "local_reasoning",
    "prepare_environment",
    "run",
    "run_many",
    "stream",
]
