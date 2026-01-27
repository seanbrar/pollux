# FAQ — Getting Started

Last reviewed: 2025-09

Answers to common first-run and onboarding questions.

## Do I need an API key to try it?

No. The library defaults to a deterministic mock mode. You can install and run the Quickstart without any credentials and get a provable success signal.

## How do I switch from mock to the real API?

Set your API key and explicitly enable real calls:

=== "Bash/Zsh"

```bash
export GEMINI_API_KEY="<your key>"
export POLLUX_USE_REAL_API=1
```

=== "PowerShell"

```powershell
$Env:GEMINI_API_KEY = "<your key>"
$Env:POLLUX_USE_REAL_API = "1"
```

Then run `pollux-config doctor` to verify readiness. For runtime checks, see How‑to → [Verify Real API](verify-real-api.md).

## Why am I getting immediate rate limits?

Your account’s billing tier gates throughput. Configure the tier in your environment to match your billing plan:

```bash
export POLLUX_TIER=free   # or: tier_1 | tier_2 | tier_3
```

Reduce concurrency if needed (config or per-call options). See How‑to → Troubleshooting.

## How do I set environment variables safely?

Create a local `.env` file (git-ignored) using `.env.example` as a template, or use your shell’s environment. Never commit real keys.

## How do I know it’s using the real API?

- `pollux-config doctor` should report no issues and `use_real_api=True`.
- Mock answers often include an `echo:` pattern. Real answers do not.

## Does it work on Windows?

Yes. Use Python 3.13 and prefer WSL for parity with Linux/macOS. PowerShell examples are provided for env vars.

## Where can I find runnable examples?

- Tutorials → [Quickstart](../tutorials/quickstart.md) for a copy‑paste first run.
- The repository’s `cookbook/` contains 25+ practical recipes.

## How do I run cookbook recipes?

- List recipes: `python -m cookbook --list`
- Run by path: `python -m cookbook getting-started/analyze-single-paper.py -- --limit 1`
- Run by dotted spec: `python -m cookbook production.resume_on_failure -- --limit 2`
- Pass recipe flags after `--`. The runner defaults to the repo root as CWD; opt out with `--no-cwd-repo-root`.

## I still need help

Run `pollux-config show` and `pollux-config doctor` and include the output in an issue. See How‑to → [Troubleshooting](troubleshooting.md) for more.
