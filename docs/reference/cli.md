# CLI — pollux-config and Cookbook Runner

Minimal CLIs for configuration diagnostics and running repository recipes.

## Overview

- `pollux-config`: Installed console script for inspecting and validating effective configuration. Secrets are never printed; sensitive values appear as `***redacted***`.
- `python -m cookbook`: Module runner for executing recipes under `cookbook/` without setting `PYTHONPATH`.

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
  - Shows each field’s origin (default, home, project, env, overrides).
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

## Tips

- CI usage: `pollux-config show` and `pollux-config doctor` always exit `0`; parse output for warnings or raise in your pipeline if necessary.
- Redaction: `api_key` and other sensitive fields are always redacted by design.
- See also: [How‑to → Configuration](../how-to/configuration.md) for precedence rules and audit details.

## CI usage examples

Shell (fail build if API key required but missing):

```bash
if pollux-config doctor | grep -q "api_key is missing"; then
  echo "❌ Missing API key while use_real_api=True" >&2
  exit 1
fi
```

Python (doctest‑style):

```pycon
>>> import subprocess
>>> out = subprocess.check_output(["pollux-config", "doctor"], text=True)
>>> "api_key is missing" not in out
True
```

Last reviewed: 2025-09

## Cookbook Runner

- Command: `python -m cookbook [--cwd-repo-root|--no-cwd-repo-root] [--list] <spec> [-- recipe_args]`
- Spec forms:
  - Path relative to repo: `cookbook/production/resume-on-failure.py`
  - Path relative to `cookbook/`: `production/resume-on-failure.py`
  - Dotted (maps `_` → `-` on disk): `production.resume_on_failure`
- Default working directory: repository root. Opt out with `--no-cwd-repo-root`.
- Pass recipe flags after `--` (everything after is forwarded to the recipe).

Examples:

```bash
# List available recipes
python -m cookbook --list

# Run via path and pass recipe args
python -m cookbook optimization/context-caching-explicit -- --limit 2

# Run via dotted spec
python -m cookbook production.resume_on_failure -- --limit 1
```

Notes:

- Ensure you run from the repository root when using relative inputs/outputs, or rely on the default `--cwd-repo-root` behavior.
- Recipes are excluded from helper directories (`utils/`, `templates/`, `data/`).

### Cross-platform usage

=== "Bash/Zsh (macOS/Linux)"

```bash
python -m cookbook --list
python -m cookbook optimization/context-caching-explicit -- --limit 2
python -m cookbook production.resume_on_failure -- --limit 1
```

=== "PowerShell (Windows)"

```powershell
# Prefer the dotted form for portability
py -m cookbook --list
py -m cookbook optimization.context_caching_explicit -- --limit 2
py -m cookbook production.resume_on_failure -- --limit 1

# You can also use paths; forward slashes work cross‑platform
py -m cookbook optimization/context-caching-explicit.py -- --limit 2
```

=== "CMD (Windows)"

```bat
py -m cookbook --list
py -m cookbook optimization\context-caching-explicit.py -- --limit 2
py -m cookbook production.resume_on_failure -- --limit 1
```

Tips:

- Use the dotted spec (e.g., `production.resume_on_failure`) for consistency across shells.
- Pass recipe arguments after `--`; everything after is forwarded to the recipe unchanged.
- The runner defaults to executing from the repository root; opt out with `--no-cwd-repo-root` when needed.
