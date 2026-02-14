# CLI - Cookbook Runner

Pollux currently ships one documented CLI surface:

- `python -m cookbook`: run recipes under `cookbook/` without manual `PYTHONPATH` setup.

## Prerequisites

Install dev dependencies so recipe imports resolve correctly:

```bash
uv sync --all-extras          # installs all dev/test/docs/lint deps
```

## Command Shape

```bash
python -m cookbook [--list] [--cwd-repo-root|--no-cwd-repo-root] [<spec>] [recipe_args...]
```

- `--list`: list available recipes and exit.
- `<spec>`: recipe identifier to run.
- `recipe_args...`: args forwarded to the selected recipe.
- `--cwd-repo-root` (default): run recipes from repo root.
- `--no-cwd-repo-root`: keep current working directory.

If you include `--`, everything after it is forwarded to the recipe unchanged.

## Spec Forms

The runner accepts several equivalent recipe spec forms:

- Repo-relative path: `cookbook/production/resume-on-failure.py`
- Cookbook-relative path: `production/resume-on-failure.py`
- Dotted form (`_` maps to `-`): `production.resume_on_failure`

## Common Commands

```bash
# List recipes
python -m cookbook --list

# Bare invocation prints a welcome message and quick-start commands
python -m cookbook

# Run by cookbook-relative path
python -m cookbook optimization/cache-warming-and-ttl --limit 2 --ttl 3600

# Run by dotted spec
python -m cookbook production.resume_on_failure --limit 1

# Explicit passthrough separator
python -m cookbook getting-started/analyze-single-paper -- --help
```

## Recipe Help

The runner forwards `--help` to a recipe when a valid recipe spec comes first:

```bash
python -m cookbook getting-started/analyze-single-paper --help
```

## Cross-Platform Notes

=== "Bash/Zsh (macOS/Linux)"

```bash
python -m cookbook --list
python -m cookbook optimization/cache-warming-and-ttl --limit 2 --ttl 3600
python -m cookbook production.resume_on_failure --limit 1
```

=== "PowerShell (Windows)"

```powershell
py -m cookbook --list
py -m cookbook optimization.cache_warming_and_ttl --limit 2 --ttl 3600
py -m cookbook production.resume_on_failure --limit 1
```

=== "CMD (Windows)"

```bat
py -m cookbook --list
py -m cookbook optimization\\cache-warming-and-ttl.py -- --limit 2 --ttl 3600
py -m cookbook production.resume_on_failure --limit 1
```

## Troubleshooting

- `could not import pollux`: run `uv sync --all-extras`.
- `Recipe not found`: verify the spec with `python -m cookbook --list`.
- Unexpected relative-path behavior: use `--no-cwd-repo-root` only when you need CWD-local paths.
