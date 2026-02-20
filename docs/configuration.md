# Configuration

Pollux uses an explicit `Config` object per call. No global state, no
implicit defaults.

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
| `provider` | `"gemini" \| "openai"` | *(required)* | Provider to use |
| `model` | `str` | *(required)* | Model identifier |
| `api_key` | `str \| None` | `None` | Explicit key; auto-resolved from env if omitted |
| `use_mock` | `bool` | `False` | Use mock provider (no network calls) |
| `enable_caching` | `bool` | `False` | Enable provider-side context caching |
| `ttl_seconds` | `int` | `3600` | Cache time-to-live in seconds |
| `request_concurrency` | `int` | `6` | Max concurrent API calls in multi-prompt execution |
| `retry` | `RetryPolicy` | `RetryPolicy()` | Retry configuration |

## API Key Resolution

If `api_key` is omitted, Pollux resolves it from environment variables:

- Gemini: `GEMINI_API_KEY`
- OpenAI: `OPENAI_API_KEY`

```bash
export GEMINI_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

You can also pass a key directly:

```python
config = Config(provider="openai", model="gpt-5-nano", api_key="sk-...")
```

Pollux auto-loads `.env` files via `python-dotenv`. Create a `.env` in your
project root for local development — but never commit it.

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
    enable_caching=True,       # Reuse uploaded context (Gemini-only in v1.0)
    ttl_seconds=3600,          # Cache lifetime
    request_concurrency=6,     # Concurrent API calls
)
```

| Need | Direction |
|---|---|
| Fast iteration without API calls | `use_mock=True` |
| Reduce token spend on repeated context | `enable_caching=True` |
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

## Options

`Options` controls per-call execution features:

```python
from pollux import Options

options = Options(
    system_instruction="You are a concise analyst.",  # Optional global behavior guide
    response_schema=MyPydanticModel,  # Structured output extraction
    reasoning_effort="medium",        # Reserved for future provider support
    delivery_mode="realtime",         # "deferred" reserved for future provider batch APIs
)
```

See [Sources and Patterns](sources-and-patterns.md#structured-output) for
a complete structured output example.

Conversation options are provider-dependent in v1.1: OpenAI supports
`history`/`continue_from`; Gemini remains unsupported.

## Safety Notes

- `Config` is immutable (`frozen=True`). Create a new instance to change values.
- `Config` validates the provider name on init — unknown providers raise
  `ConfigurationError` immediately rather than failing at call time.
- String representation redacts API keys.
- Missing keys in real mode raise `ConfigurationError` with actionable hints.

## Dev Install (Contributors)

See [Contributing](contributing.md) for full development setup instructions.
