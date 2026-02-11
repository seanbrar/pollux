# Configuration

Pollux v1.0 uses an explicit `Config` object per call.

## Use this page when

- You want predictable provider/model selection.
- You need to tune cost, latency, retries, or caching behavior.
- You need local mock runs before real API usage.

## Core Pattern

```python
from pollux import Config

config = Config(
    provider="gemini",          # "gemini" | "openai"
    model="gemini-2.5-flash-lite",
)
```

## Quick Decision Guide

| Need | Configuration direction |
|---|---|
| Fast local iteration without API calls | `use_mock=True` |
| Real provider calls | set provider-specific API key and `use_mock=False` (default) |
| Repeated questions over shared context | `enable_caching=True` (provider-dependent) |
| Higher throughput for many prompts/sources | tune `request_concurrency` |
| Better resilience to transient API failures | customize `retry=RetryPolicy(...)` |

## Provider-specific caveats

- Context caching is currently Gemini-only in v1.0.
- Feature availability can differ by provider/model.
- Always confirm assumptions against
  [Provider Capabilities](../reference/provider-capabilities.md).

## API Keys

If `api_key` is omitted, Pollux resolves it from environment variables:

- Gemini -> `GEMINI_API_KEY`
- OpenAI -> `OPENAI_API_KEY`

```bash
export GEMINI_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

You can also pass `api_key` directly:

```python
config = Config(provider="openai", model="gpt-5-nano", api_key="...")
```

## Mock Mode

Use `use_mock=True` for local development without external API calls:

```python
config = Config(provider="gemini", model="mock-model", use_mock=True)
```

## Performance/Cost Controls

```python
config = Config(
    provider="gemini",
    model="gemini-2.5-flash-lite",
    enable_caching=True,     # provider-dependent
    ttl_seconds=3600,        # cache TTL
    request_concurrency=6,   # concurrent requests in multi-prompt execution
)
```

## Retries

Pollux retries transient provider failures with exponential backoff, full
jitter, and a wall-clock deadline. Customize via `RetryPolicy`:

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
|-------|---------|-------------|
| `max_attempts` | `2` | Total attempts (including the first call) |
| `initial_delay_s` | `0.5` | Delay before the first retry |
| `backoff_multiplier` | `2.0` | Multiplier applied to the delay after each retry |
| `max_delay_s` | `5.0` | Upper bound on any single retry delay |
| `jitter` | `True` | Apply full jitter (`random(0, delay)`) to avoid thundering herd |
| `max_elapsed_s` | `15.0` | Wall-clock deadline across all attempts; `None` to disable |

When a provider returns a `Retry-After` hint, Pollux respects it (using
whichever is longer: the computed backoff or the server hint).

## Safety Notes

- `Config` is immutable (`frozen=True`).
- String representation redacts API keys.
- Missing keys in real mode raise `ConfigurationError` with hints.

## Success check

A valid config should construct without exceptions and print with redacted keys:

```python
from pollux import Config

config = Config(provider="gemini", model="gemini-2.5-flash-lite", use_mock=True)
print(config)
```

## Related Docs

- [Concepts](../concepts.md)
- [Installation](installation.md)
- [Usage Patterns](patterns.md)
- [Provider Capabilities](../reference/provider-capabilities.md)
