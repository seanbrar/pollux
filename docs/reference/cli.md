# CLI - pollux-config and Cookbook Runner

Two small CLIs for diagnostics and running recipes.

## Overview

- `pollux-config`: Inspect effective configuration (secrets are redacted).
- `python -m cookbook`: Run recipes under `cookbook/` without `PYTHONPATH`.

## `pollux-config` Commands

- `pollux-config show`: Prints the effective, redacted config as JSON.
  - Use when you need a machine-readable snapshot for logs or CI artifacts.
  - Example:

    ```bash
    pollux-config show
    # {
    #   "model": "gemini-2.0-flash",
    #   "api_key": "***redacted***",
    #   "use_real_api": false,
    #   "enable_caching": false,
    #   "ttl_seconds": 3600,
    #   "telemetry_enabled": false,
    #   "tier": "free",
    #   "provider": "google",
    #   "extra": {}
    # }
    ```

- `pollux-config audit`: Prints a human-readable audit and a layer summary.
  - Shows each field's origin (default, home, project, env, overrides).
  - Example (truncated):

    ```bash
    pollux-config audit
    # model: gemini-2.0-flash (default)
    # tier: free (default)
    # ...
    # default  : N fields
    # home     : 0 fields
    # project  : 0 fields
    # env      : M fields
    # overrides: 0 fields
    ```

- `pollux-config doctor`: Prints actionable messages and advisories.
  - Use to confirm readiness before running real API calls.
  - Example:

    ```bash
    pollux-config doctor
    # No issues detected.
    # Advisory: 'tier' not specified; using default FREE. See: tier (enum: FREE|TIER_1|...)
    ```

- `pollux-config env`: Prints relevant environment variables (redacted where needed).
  - Includes both `POLLUX_*` and `GEMINI_*` variables.
  - Example:

    ```bash
    pollux-config env | sort
    # GEMINI_API_KEY=***redacted***
    # POLLUX_TIER=free
    # POLLUX_USE_REAL_API=1
    ```

See [Configuration](../guides/configuration.md) for precedence rules and common
setup patterns.

## Cookbook Runner

### Prerequisites

The cookbook runner requires a dev install so that recipe imports resolve correctly:

```bash
uv sync --all-extras          # or: pip install -e ".[dev]"
```

- Command: `python -m cookbook [--cwd-repo-root|--no-cwd-repo-root] [--list] <spec> [[--] recipe_args...]`
- Spec forms:
  - Path relative to repo: `cookbook/production/resume-on-failure.py`
  - Path relative to `cookbook/`: `production/resume-on-failure.py`
  - Dotted (maps `_` -> `-` on disk): `production.resume_on_failure`
- Default working directory: repository root. Opt out with `--no-cwd-repo-root`.
- Recipe flags can be passed directly after the spec (recommended for most shells).
- If you prefer explicit separation, include `--` and everything after is forwarded to the recipe unchanged.

Examples:

```bash
# List available recipes
python -m cookbook --list

# Run via path and pass recipe args (no separator required)
python -m cookbook optimization/cache-warming-and-ttl --limit 2 --ttl 3600

# Optional explicit separator
python -m cookbook optimization/cache-warming-and-ttl -- --limit 2 --ttl 3600

# Run via dotted spec
python -m cookbook production.resume_on_failure --limit 1
```

Notes:

- Ensure you run from the repository root when using relative inputs/outputs, or rely on the default `--cwd-repo-root` behavior.
- Recipes are excluded from helper directories (`utils/`, `templates/`, `data/`).

### Cross-platform usage

=== "Bash/Zsh (macOS/Linux)"

```bash
python -m cookbook --list
python -m cookbook optimization/cache-warming-and-ttl --limit 2 --ttl 3600
python -m cookbook production.resume_on_failure --limit 1
```

=== "PowerShell (Windows)"

```powershell
# Prefer the dotted form for portability
py -m cookbook --list
py -m cookbook optimization.cache_warming_and_ttl --limit 2 --ttl 3600
py -m cookbook production.resume_on_failure --limit 1

# You can also use paths; forward slashes work cross-platform
py -m cookbook optimization/cache-warming-and-ttl.py -- --limit 2 --ttl 3600
```

=== "CMD (Windows)"

```bat
py -m cookbook --list
py -m cookbook optimization\\cache-warming-and-ttl.py -- --limit 2 --ttl 3600
py -m cookbook production.resume_on_failure --limit 1
```

Tips:

- Use the dotted spec (e.g., `production.resume_on_failure`) for consistency across shells.
- You can pass recipe arguments directly after the spec, or place `--` before recipe args for explicit separation.
- The runner defaults to executing from the repository root; opt out with `--no-cwd-repo-root` when needed.
