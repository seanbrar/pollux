# Configuration

Set a few values and Pollux will pick sensible defaults for the rest. This guide
shows the three most common ways to configure behavior.

## 1) Environment variables (quickest)

Goal: Run with the real API and pick a model.

```bash
export GEMINI_API_KEY="<your key>"
export POLLUX_MODEL="gemini-2.0-flash"
export POLLUX_USE_REAL_API="true"
```

```python
from pollux.config import resolve_config

config = resolve_config()
print(f"Using {config.model} with provider {config.provider}")
```

Notes:

- If `POLLUX_USE_REAL_API=true`, a key is required. Otherwise mock mode is used.
- Secrets are always redacted in diagnostics.

## 2) Project defaults in `pyproject.toml`

Goal: Share defaults across your team or CI.

```toml
# pyproject.toml
[tool.pollux]
model = "gemini-2.0-flash"
use_real_api = false
enable_caching = false
ttl_seconds = 3600
```

```python
from pollux.config import resolve_config

config = resolve_config()
print(config.model)
```

Precedence: programmatic overrides > env > project file > home file > defaults.

## 3) Profiles (per-environment presets)

Goal: Switch between dev and prod without editing code.

```toml
[tool.pollux.profiles.dev]
model = "gemini-2.0-flash"
use_real_api = false

[tool.pollux.profiles.prod]
model = "gemini-2.0-pro"
use_real_api = true
```

```bash
export POLLUX_PROFILE=prod
```

Or programmatically:

```python
from pollux.config import resolve_config

config = resolve_config(profile="dev")
```

## 4) Programmatic overrides (per-run)

Goal: Pin values for a specific run or test.

```python
from pollux.config import resolve_config

config = resolve_config(overrides={"model": "gemini-2.0-flash", "use_real_api": False})
```

## Diagnostics

Use the CLI to inspect effective configuration:

- `pollux-config show`
- `pollux-config doctor`

See the [CLI reference](../reference/cli.md) for details.
