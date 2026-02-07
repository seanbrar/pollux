# Configuration

Pollux v1.0 uses an explicit `Config` object per call.

## Core Pattern

```python
from pollux import Config

config = Config(
    provider="gemini",          # "gemini" | "openai"
    model="gemini-2.5-flash-lite",
)
```

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
    request_concurrency=6,   # concurrent requests in batch execution
)
```

## Safety Notes

- `Config` is immutable (`frozen=True`).
- String representation redacts API keys.
- Missing keys in real mode raise `ConfigurationError` with hints.

## Related Docs

- [Usage Patterns](patterns.md)
- [Provider Capabilities](../reference/provider-capabilities.md)
