<!-- Intent: Reference page for Config fields. Cover API key
     resolution, mock mode, performance/cost controls, RetryPolicy, and execution
     parameters. Do NOT include tutorials or extended examples,
     link to the relevant guide pages. Register: reference. -->

# Configuring Pollux

You need to tell Pollux which provider, model, and API key to use. The
`Config` object captures these choices explicitly. No implicit provider or
model defaults.

!!! info "Boundary"
    **Pollux owns:** validating config, resolving API keys from the
    environment, managing retry logic, and enforcing provider constraints.

    **You own:** selecting the right provider and model, managing API keys
    securely, and tuning concurrency and retry settings for your workload.

## Config Fields

```python
from pollux import Config

config = Config(
    provider="gemini",
    model="gemini-2.5-flash-lite",
)
```

All fields and their defaults:

| Field | Type | Default | Description |
|---|---|---|---|
| `provider` | `"gemini" \| "openai" \| "anthropic" \| "openrouter" \| "local"` | *(required)* | Provider to use |
| `model` | `str \| None` | `None` | Model identifier. Required for cloud providers; optional for single-model local servers |
| `api_key` | `str \| None` | `None` | Explicit key; auto-resolved from env if omitted. Optional for `provider="local"` |
| `base_url` | `str \| None` | `None` | Required for `provider="local"`; rejected for cloud providers. Falls back to `POLLUX_LOCAL_BASE_URL` |
| `use_mock` | `bool` | `False` | Use mock provider (no network calls) |
| `request_concurrency` | `int` | `6` | Max concurrent API calls in multi-prompt execution |
| `request_timeout_s` | `float` | `300.0` | HTTP request timeout in seconds for providers that own their transport, including `provider="local"` |
| `retry` | `RetryPolicy` | `RetryPolicy()` | Retry configuration |
| `capabilities` | `Mapping[str, bool] \| None` | `None` | Optional v2 interaction capability overrides, mainly for local OpenAI-compatible servers whose feature support varies |

### Field Categories

`Config` is intentionally a low-level library object. If you are building an
application or agent framework on top of Pollux, you will usually expose a
smaller product-specific selector and translate it into `Config`.

| Category | Fields | Meaning |
|---|---|---|
| Provider identity | `provider`, `model` | Which provider adapter and model Pollux should call. Cloud providers require both fields. A local OpenAI-compatible server may omit `model` when the server owns model selection. |
| Transport settings | `base_url`, `request_timeout_s` | How Pollux reaches a provider endpoint. `base_url` is only for `provider="local"` and is rejected for cloud providers. |
| Credentials | `api_key` or provider env vars | Authentication material. Pass an explicit key, or let Pollux resolve it from the provider-specific environment variable. |
| Capability overrides | `capabilities` | Advanced escape hatch for declaring provider capabilities when static provider defaults are too broad or too narrow, especially for local servers. |
| Per-execution controls | `request_concurrency`, `retry`, `use_mock` | Pollux execution behavior around concurrency, retries, and mock/no-network operation. Generation controls such as `temperature`, `max_tokens`, `reasoning_effort`, and `tool_choice` are passed to `run()`, `run_many()`, `interact()`, `stream()`, or `defer()`, not stored on `Config`. |

For application settings, keep product concerns outside Pollux. For example,
an agent harness might keep `provider = "local"` and `model = "gemma3:4b"` in
its own TOML file, then construct `Config(provider="local", model="gemma3:4b")`
at the Pollux boundary. Pollux still owns provider credential discovery and
provider validation.

## API Key Resolution

If `api_key` is omitted, Pollux resolves it from environment variables:

- Gemini: `GEMINI_API_KEY`
- OpenAI: `OPENAI_API_KEY`
- Anthropic: `ANTHROPIC_API_KEY`
- OpenRouter: `OPENROUTER_API_KEY`

```bash
export GEMINI_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
export ANTHROPIC_API_KEY="your-key"
export OPENROUTER_API_KEY="your-key"
```

You can also pass a key directly:

```python
config = Config(provider="openai", model="gpt-5-nano", api_key="sk-...")
```

If an expected environment variable is not already set, Pollux lazily asks
`python-dotenv` to load a `.env` file and checks again. A `.env` file is
convenient for local development, but it is not required: exported process
environment variables, shell profiles, secret managers, CI secrets, or explicit
`api_key=` values all work. Never commit real keys.

## Self-Hosted Models (`provider="local"`)

Pollux supports self-hosted servers that speak the OpenAI Chat Completions wire
format. Point `base_url` at the server; `api_key` is optional. If the server
has a single configured model or rejects client-supplied model names, omit
`model` and Pollux will leave the `model` request field out of local payloads.

```python
config = Config(
    provider="local",
    model="gemma3:4b",
    base_url="http://localhost:11434/v1",
    request_timeout_s=600,
)
```

Or set `POLLUX_LOCAL_BASE_URL` in your environment and omit the kwarg:

```bash
export POLLUX_LOCAL_BASE_URL="http://localhost:11434/v1"
```

```python
config = Config(provider="local", model="gemma3:4b")
```

As with API keys, `POLLUX_LOCAL_BASE_URL` can come from the process
environment, a shell profile, CI configuration, or a `.env` file. Applications
do not need to require a Pollux-specific `.env`; they can read their own
settings and pass `base_url=` directly.

The supported surface is narrow by design: text in, text or JSON out. Pollux
also surfaces model-native reasoning text when the local server returns it.
File uploads, tool calling, reasoning controls, context caching, and deferred
delivery are not supported. See
[Provider Capabilities](reference/provider-capabilities.md#local) for the full
matrix and [Writing Portable Code Across Providers](portable-code.md#running-against-a-self-hosted-model)
for swap patterns.

## Mock Mode

Use `use_mock=True` for local development without external API calls:

```python
config = Config(provider="gemini", model="gemini-2.5-flash-lite", use_mock=True)
```

Mock responses echo prompts and return synthetic metrics. Useful for validating
pipeline logic, testing integrations, and CI.

## Performance and Cost Controls

```python
config = Config(
    provider="gemini",
    model="gemini-2.5-flash-lite",
    request_concurrency=6,     # Concurrent API calls
)
```

| Need | Direction |
|---|---|
| Fast iteration without API calls | `use_mock=True` |
| Reduce token spend on repeated context | Use `prepare_environment(cache=CachePolicy(...))`. See [Reducing Costs with Context Caching](caching.md) |
| Higher throughput for many prompts/sources | Increase `request_concurrency` |
| Better resilience to transient failures | Customize `retry=RetryPolicy(...)` |

## RetryPolicy

Pollux retries transient provider failures with exponential backoff, full
jitter, and a wall-clock deadline:

```python
from pollux import RetryPolicy

config = Config(
    provider="gemini",
    model="gemini-2.5-flash-lite",
    retry=RetryPolicy(max_attempts=3, initial_delay_s=0.25),
)
```

All `RetryPolicy` fields (defaults shown):

| Field | Default | Description |
|---|---|---|
| `max_attempts` | `2` | Total attempts (including the first call) |
| `initial_delay_s` | `0.5` | Delay before the first retry |
| `backoff_multiplier` | `2.0` | Multiplier applied after each retry |
| `max_delay_s` | `5.0` | Upper bound on any single retry delay |
| `jitter` | `True` | Full jitter to avoid thundering herd |
| `max_elapsed_s` | `15.0` | Wall-clock deadline; `None` to disable |

When a provider returns a `Retry-After` hint, Pollux respects it (whichever
is longer: the computed backoff or the server hint).

## Execution and Generation Parameters

In Pollux v2, generation and execution constraints are passed as first-class keyword arguments to the execution functions (`run()`, `run_many()`, `interact()`, `stream()`, and `defer()`).

For stable setups (such as tools, system instructions, or caching policies), you define them on a reusable `Environment`. Per-turn inputs (conversation state, tool results, prompt content) are passed via `Input`.

Here is an example showing the keyword arguments you can pass directly:

```python
# Pass options as direct kwargs
result = await run(
    "Solve this problem.",
    config=config,
    output=MyPydanticModel,           # Structured output schema
    temperature=0.7,                  # Generation tuning
    top_p=0.9,                        # Generation tuning
    max_tokens=4096,                  # Output token ceiling
    seed=123,                         # Sampling seed where supported
    reasoning_effort="medium",        # Qualitative thinking depth
    # reasoning_budget_tokens=2048,   # Or explicit thinking token budget
    tool_choice="auto",               # Tool-choice control
    provider_options={                # Raw provider escape hatch
        "openai": {"tools": [{"type": "web_search_preview"}]},
    },
)
```

### Supported Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `output` | `type[BaseModel] \| dict \| None` | `None` | Expected JSON response format. See [Extracting Structured Data](structured-data.md) |
| `temperature` | `float \| None` | `None` | Sampling temperature |
| `top_p` | `float \| None` | `None` | Nucleus sampling probability |
| `max_tokens` | `int \| None` | `None` | Output-token budget cap |
| `seed` | `int \| None` | `None` | Optional sampling seed |
| `reasoning_effort` | `str \| None` | `None` | Qualitative reasoning level (`"low"`, `"medium"`, `"high"`). See [Writing Portable Code Across Providers](portable-code.md#choosing-a-reasoning-control) |
| `reasoning_budget_tokens` | `int \| None` | `None` | Explicit reasoning token budget. See [Writing Portable Code Across Providers](portable-code.md#choosing-a-reasoning-control) |
| `tool_choice` | `str \| dict \| None` | `None` | Tool-choice control (`"auto"`, `"required"`, `"none"`, or dict). See [Building an Agent Loop](agent-loop.md) |
| `provider_options` | `dict[str, dict] \| None` | `None` | Raw provider-scoped request options. Keys must be provider names. |

### Environment Configuration

For instructions, sources, and tool declarations, configure an `Environment` and pass it to `interact()`, `run()`, or `run_many()`:

```python
from pollux import Environment, ToolDeclaration, CachePolicy

env = Environment(
    instructions="You are a helpful assistant.",
    sources=[Source.from_file("doc.pdf")],
    tools=[ToolDeclaration(name="get_weather", description="...")],
    cache=CachePolicy(ttl_seconds=3600), # Persistent caching policy
)
```

Or for `run()` and `run_many()`, you can pass `instructions`, `sources` / `source`, and `tools` directly as inline keyword arguments, and Pollux will construct the `Environment` internally.

### Provider Options Escape Hatch

`provider_options` is Pollux's one raw provider escape hatch. It is for provider-specific request fields that Pollux does not normalize, such as hosted/server tools, service tiers, or newly released provider knobs.

```python
result = await run(
    prompt,
    config=config,
    provider_options={
        "openai": {"tools": [{"type": "web_search_preview"}]},
        "gemini": {"seed": 123},
    },
)
```

Only the active provider's dictionary is forwarded. If a raw key overlaps with a field Pollux already generated from first-class options, Pollux raises `ConfigurationError` instead of silently overriding either value. For example, do not pass both `tools=[...]` and `provider_options={"openai": {"tools": [...]}}` in the same call.

!!! note
    OpenAI GPT-5 family models (`gpt-5`, `gpt-5-mini`, `gpt-5-nano`) reject sampling controls like `temperature` and `top_p` with provider errors. Older OpenAI models (for example `gpt-4.1-nano`) still accept them. See [Writing Portable Code Across Providers](portable-code.md#model-specific-constraints) for the full constraints mapping.

!!! note
    `reasoning_effort` and `reasoning_budget_tokens` are mutually exclusive. Use `reasoning_effort` when the provider exposes named levels (`"low"`, `"medium"`, `"high"`). Use `reasoning_budget_tokens` when you need an exact token ceiling. Not every provider accepts both, and some provider/model combinations may still reject a value at call time; see [Reasoning Control Mapping](portable-code.md#reasoning-control-mapping).

!!! note
    `max_tokens` is not a portable "length knob" with identical behavior everywhere. Anthropic uses it as the total output budget and applies a provider default when you omit it. OpenRouter forwards it to the routed model. Other providers may ignore it in the current release.

!!! warning "Cache environment restrictions"
    When persistent `cache` is configured on an `Environment`, `instructions` and `tools` are baked directly into the cache. Modifying them requires preparing a new `Environment` (which creates a new cache). See [Reducing Costs with Context Caching](caching.md) for details.

## Safety Notes

- `Config` is immutable (`frozen=True`). Create a new instance to change values.
- `Config` validates the provider name on init. Unknown providers raise
  `ConfigurationError` immediately rather than failing at call time.
- String representation redacts API keys.
- Missing keys in real mode raise `ConfigurationError` with actionable
  hints.

## Dev Install (Contributors)

See [Contributing](contributing.md) for full development setup instructions.

---

For the full provider feature matrix and model-specific constraints, see
[Provider Capabilities](reference/provider-capabilities.md) and
[Writing Portable Code Across Providers](portable-code.md). For the deferred
workflow, see [Submitting Work for Later Collection](submitting-work-for-later-collection.md).
