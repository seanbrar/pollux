<!-- Intent: Teach portability patterns: separating provider-specific details
     from pipeline logic, graceful degradation, model tier mapping, and testing
     with mock mode. Cover model-specific constraints (GPT-5 sampling, Gemini
     reasoning). Do NOT re-explain tool calling or conversation mechanics.
     Assumes the reader has used run() and understands Config/Options.
     Register: guided applied (architectural patterns). -->

# Writing Portable Code Across Providers

You want analysis code that works across providers. Switch from Gemini to
OpenAI (or back) by changing a config line, not rewriting your pipeline.
This page shows the patterns that make that work.

Pollux is capability-transparent, not capability-equalizing. All providers
support the core text pipeline, but some features are provider-specific. For
example, Gemini uses explicit cache handles (`create_cache()`), Anthropic uses
implicit caching (`Options(implicit_caching=True)`), and OpenRouter exposes
tool calling and structured outputs only on models that advertise those
features.
When you use an unsupported feature for a provider, Pollux raises a
`ConfigurationError` or `APIError`. No silent degradation.
This keeps behavior legible in both development and production.

!!! info "Boundary"
    **Pollux owns:** translating your `Config`, `Options`, `Source`, and
    prompts into provider-specific API calls, and normalizing responses
    into a stable `ResultEnvelope`.

    **You own:** choosing which features to use (sticking to the portable
    subset or gracefully degrading), selecting provider-appropriate models,
    and handling capability differences at the edges.

## The Pattern

Portable code separates what varies (provider, model, provider-specific
options) from what doesn't (prompts, sources, pipeline logic). Put the
varying parts in config; keep the stable parts in functions.

## Complete Example

A document analysis function that works on any provider.

```python
import asyncio
from dataclasses import dataclass

from pydantic import BaseModel

from pollux import Config, ConfigurationError, Options, Source, run


class DocumentSummary(BaseModel):
    title: str
    key_points: list[str]
    word_count: int


@dataclass
class ProviderConfig:
    """Maps a provider to a model."""
    provider: str
    model: str


# Provider-specific details live here, not in your pipeline logic
PROVIDERS = {
    "gemini": ProviderConfig("gemini", "gemini-2.5-flash-lite"),
    "openai": ProviderConfig("openai", "gpt-5-nano"),
    "anthropic": ProviderConfig("anthropic", "claude-haiku-4-5"),
    "openrouter": ProviderConfig("openrouter", "openai/gpt-5-nano"),
}


def make_config(provider_name: str) -> Config:
    """Build a Config for the given provider with safe defaults."""
    pc = PROVIDERS[provider_name]
    return Config(provider=pc.provider, model=pc.model)


async def analyze_document(
    file_path: str,
    prompt: str,
    *,
    provider_name: str = "gemini",
) -> DocumentSummary:
    """Analyze a document — works with any supported provider."""
    config = make_config(provider_name)
    options = Options(response_schema=DocumentSummary)

    result = await run(
        prompt,
        source=Source.from_file(file_path),
        config=config,
        options=options,
    )
    return result["structured"][0]


async def main() -> None:
    prompt = "Summarize this document with key points and a word count estimate."

    # Same function, different providers
    for provider in ["gemini", "openai", "anthropic", "openrouter"]:
        try:
            summary = await analyze_document(
                "report.pdf", prompt, provider_name=provider,
            )
            print(f"[{provider}] {summary.title}: {len(summary.key_points)} points")
        except ConfigurationError as exc:
            print(f"[{provider}] Skipped: {exc.hint}")


asyncio.run(main())
```

### Step-by-Step Walkthrough

1. **Centralize provider details.** `ProviderConfig` maps each provider to
   its model. Your analysis functions never reference provider names or
   models directly.

2. **Handle features conditionally.** Explicit caching (`create_cache()`) is
   Gemini-specific, while implicit caching (`implicit_caching=True`) is Anthropic-specific. Handle conditional optimizations near the edge, or wrap them dynamically if needed.

3. **Write provider-agnostic functions.** `analyze_document` accepts a
   provider name and builds the config internally. The prompt, source, and
   schema are the same regardless of provider.

4. **Handle config errors at the edge.** The `main` function catches
   `ConfigurationError` and logs a skip. This is the right place for
   provider-specific fallback logic.

## Model-Specific Constraints

Pollux provides a unified interface, but the models underneath have their
own constraints. Some reject tuning parameters. Others introduce features
that don't map to traditional controls.

### GPT-5 Family Rejects Sampling Controls

OpenAI's `gpt-5` family (`gpt-5`, `gpt-5-mini`, `gpt-5-nano`) rejects
`temperature` and `top_p` sampling controls with a provider error. Older
models (like `gpt-4.1-nano`) still accept them.

```python
# This will fail with a ProviderError for gpt-5 family models
options = Options(temperature=0.8, top_p=0.9)

# Instead, use the default behavior or rely on reasoning_effort
options = Options(reasoning_effort="medium")
```

### Gemini 2.5 and Reasoning Controls

Gemini 2.x models use dynamic reasoning internally but do not accept the
`reasoning_effort` option directly. Setting it on a `gemini-2.5` model
results in a provider error. Gemini 3 models (`gemini-3-flash-preview`)
do accept reasoning controls.

```python
# Works with Gemini 3 models
result = await run(
    "Solve this step by step...",
    config=Config(provider="gemini", model="gemini-3-flash-preview"),
    options=Options(reasoning_effort="high"),
)

if "reasoning" in result:
    for text in result["reasoning"]:
        if text:
            print("Thinking:", text)
```

### Reasoning Control Mapping

| Provider | Model Family | Valid `reasoning_effort` values | Provider Behavior |
| --- | --- | --- | --- |
| **OpenAI** | `gpt-5` family | `"low"`, `"medium"`, `"high"` | Returns a reasoning summary |
| **Gemini** | `gemini-3` family | `"low"`, `"medium"`, `"high"`, `"minimal"` | Returns full thinking text |
| **Gemini** | `gemini-2.5` family | *N/A (raises error)* | *N/A* |
| **Anthropic** | `claude-4.x` family | `"low"`, `"medium"`, `"high"`, `"max"` (Opus 4.6 only) | Returns thinking text and preserves replay blocks for tool loops |

## Variations

### Provider-specific model selection

Different providers have different model tiers. Map your quality/cost/speed
preferences to provider-specific models:

```python
MODEL_TIERS = {
    "fast": {"gemini": "gemini-2.5-flash-lite", "openai": "gpt-5-nano", "anthropic": "claude-haiku-4-5"},
    "balanced": {"gemini": "gemini-2.5-flash", "openai": "gpt-5-mini", "anthropic": "claude-sonnet-4-6"},
    "quality": {"gemini": "gemini-2.5-pro", "openai": "gpt-5", "anthropic": "claude-opus-4-6"},
}


def make_config_tiered(provider: str, tier: str = "fast") -> Config:
    model = MODEL_TIERS[tier][provider]
    return Config(provider=provider, model=model)
```

### Graceful degradation for optional features

Some features work on one provider but not another. Wrap them in try/except
at the call site rather than avoiding them entirely:

```python
async def analyze_with_reasoning(
    file_path: str, prompt: str, *, provider_name: str,
) -> tuple[str, str | None]:
    """Analyze with reasoning when supported; fall back to plain analysis."""
    config = make_config(provider_name)

    try:
        result = await run(
            prompt,
            source=Source.from_file(file_path),
            config=config,
            options=Options(reasoning_effort="high"),
        )
        reasoning = None
        if "reasoning" in result and result["reasoning"][0]:
            reasoning = result["reasoning"][0]
        return result["answers"][0], reasoning

    except ConfigurationError:
        # Provider doesn't support reasoning — retry without it
        result = await run(
            prompt,
            source=Source.from_file(file_path),
            config=config,
        )
        return result["answers"][0], None
```

### Testing portability

Use mock mode to validate pipeline logic without API calls, then test each
provider in CI with real credentials:

```python
import pytest

@pytest.mark.parametrize("provider", ["gemini", "openai", "anthropic"])
async def test_analyze_document_mock(provider: str) -> None:
    config = Config(provider=provider, model="any-model", use_mock=True)
    result = await run(
        "Summarize this.",
        source=Source.from_text("Test content."),
        config=config,
    )
    assert result["status"] == "ok"
    assert len(result["answers"]) == 1
```

## What to Watch For

- **Keep the portable subset in mind.** Text generation and conversation
  continuity work on all providers. Structured output and tool calling are
  portable across Gemini, OpenAI, and Anthropic; OpenRouter supports them only
  on models that advertise the required parameters. Context caching has
  different paradigms (explicit for Gemini, implicit for Anthropic). YouTube
  URLs have limited OpenAI and Anthropic support. Check
  [Provider Capabilities](reference/provider-capabilities.md).
- **Config errors are your portability signal.** A `ConfigurationError` for
  an unsupported feature marks the boundary of portability. Handle it at
  the call site.
- **Model names are provider-specific.** Never hardcode model names in your
  pipeline logic. Keep them in config or a lookup table.
- **Sampling controls vary.** OpenAI GPT-5 family models reject `temperature`
  and `top_p`. If you use these, guard them with a provider check or catch
  the error.
- **Test with mock first.** `use_mock=True` validates your pipeline structure
  without API calls. All providers return synthetic responses in mock mode.

---

For handling the errors that portability checks surface (`ConfigurationError`,
`APIError`), see [Handling Errors and Recovery](error-handling.md).
