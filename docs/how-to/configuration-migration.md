# Configuration System Migration Guide

This guide covers the enhanced configuration system using the **Pydantic Two-File Core** pattern.

## Quick Migration

### Current System

```python
from pollux.config import resolve_config

# Direct FrozenConfig - clean and simple
config = resolve_config()
model = config.model
api_key = config.api_key
provider = config.provider  # Auto-inferred via enhanced provider inference
extra = config.extra  # Validated extra fields
```

### Replacing legacy ambient usage

The old `ambient()` helper has been removed. Replace it with explicit resolution and (when needed) scoped overrides:

```python
from pollux.config import resolve_config, config_scope

config = resolve_config()

# Scoped overrides at resolution time
with config_scope({"model": "test-model"}):
    cfg = resolve_config()
```

### Advanced Usage

```python
from pollux.config import resolve_config

# With overrides
config = resolve_config(overrides={"model": "gpt-4o"})

# With audit trail
config, sources = resolve_config(explain=True)
print(f"Model came from: {sources['model'].origin}")

# Provider is inferred automatically from the model name
```

## Configuration Introspection

Debug and understand your configuration:

```python
from pollux.config import resolve_config, check_environment, doctor

# Check current environment variables
env_vars = check_environment()
print("POLLUX_ environment variables:", env_vars)

# Get diagnostic information
diagnostics = doctor()
for message in diagnostics:
    print(f"🔍 {message}")

# Audit configuration sources
config, sources = resolve_config(explain=True)
print(f"Model '{config.model}' came from: {sources['model'].origin}")

# Debug provider inference
from pollux.config import resolve_provider
print(f"Model 'custom-llm' resolves to: {resolve_provider('custom-llm')}")
```

## Enhanced Features

1. **Immutable Configuration**: Config objects are frozen after resolution
2. **Explicit Sources**: Track where each config value came from
3. **Type Safety**: Strong typing with Pydantic validation
4. **Provider Inference**: Priority-based regex rules
5. **Extra Fields Validation**: Pattern-based validation with helpful warnings
6. **Pydantic Validation**: Rich error messages and automatic type coercion
7. **Security**: API keys are redacted in string representations
8. **Precedence**: Programmatic > Environment > Project > Home > Defaults

## Migration Checklist

- [ ] Use `resolve_config()` (ambient helper removed)
- [ ] Understand provider inference patterns for multi-provider support
- [ ] Add extra fields with conventional naming patterns (`*_timeout`, `*_url`, etc.)
- [ ] Use `explain=True` for debugging configuration issues
- [ ] Set up profile-based configuration in `pyproject.toml`

## Environment Variables

Enhanced environment variable support with automatic type coercion:

- `GEMINI_API_KEY` — Your API key (redacted in all outputs)
- `POLLUX_MODEL` — Model name (default: gemini-2.0-flash)
- `POLLUX_TIER` — API tier (`free`, `tier_1`, `tier_2`, `tier_3`)
- `POLLUX_USE_REAL_API` — Use real API (`true`/`false`, default: false)
- `POLLUX_ENABLE_CACHING` — Enable caching (`true`/`false`, default: false)
- `POLLUX_TTL_SECONDS` — Cache TTL in seconds (default: 3600)
- `POLLUX_TELEMETRY_ENABLED` — Enable telemetry (`true`/`false`, default: false)
- `POLLUX_REQUEST_CONCURRENCY` — Client-side fan-out bound (int, default: 6)
- `POLLUX_PROFILE` — Select configuration profile
- `POLLUX_DEBUG_CONFIG` — Enable redacted debug audit emission (development only)

## File-Based Configuration

Enhanced support for `pyproject.toml` and home configuration:

### pyproject.toml

```toml
[tool.pollux]
model = "gemini-2.0-flash"
use_real_api = false
enable_caching = false

# Custom fields with conventional patterns
request_timeout = 30  # *_timeout pattern
api_url = "https://api.example.com"  # *_url pattern

[tool.pollux.profiles.dev]
model = "gemini-2.0-flash"
experimental_features = true  # experimental_* pattern

[tool.pollux.profiles.prod]
model = "gemini-2.0-pro"
use_real_api = true
```

### ~/.config/pollux.toml

```toml
[tool.pollux]
model = "gemini-2.0-flash"
tier = "free"

[tool.pollux.profiles.personal]
model = "gemini-2.0-pro"
```

## Best Practices

1. **Use profiles** for environment-specific configuration
2. **Follow naming patterns** for extra fields (`*_timeout`, `*_url`, `experimental_*`)
3. **Avoid deprecated patterns** (`legacy_*` fields trigger warnings)
4. **Debug with explain=True** to understand configuration sources
5. **Rely on provider inference** for multi-provider applications

For detailed configuration reference, see the configuration documentation.
