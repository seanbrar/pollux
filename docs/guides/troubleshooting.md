# Troubleshooting

Common issues and quick fixes when getting started.

## Real API enabled but no key

- Symptom: `pollux-config doctor` prints `use_real_api=True but api_key is missing.` or calls behave like mock.
- Fix: Set `GEMINI_API_KEY` and enable real API, or disable real API.
  - `export GEMINI_API_KEY="<your key>"`
  - `export POLLUX_USE_REAL_API=1` (or unset to stay in mock mode)

## Hitting rate limits immediately

- Symptom: Slow or throttled requests after enabling real API.
- Fix: Set your billing tier to match your account; optionally reduce fan‑out.
  - `export POLLUX_TIER=free|tier_1|tier_2|tier_3`
  - Lower concurrency for vectorized calls via config or options
    - Config: `request_concurrency` in your config file or env
    - Per call: `make_execution_options(request_concurrency=1)`

## Model/provider mismatch

- Symptom: `Unknown model; provider defaulted to 'google'.`
- Fix: Use a valid model string for your provider (e.g., `gemini-2.0-flash`).

## “Mock” answers when expecting real results

- Symptom: Outputs look like `echo: ...` or include `mock` metadata.
- Fix: Ensure real API is enabled and key is present:
  - `export POLLUX_USE_REAL_API=1`
  - `export GEMINI_API_KEY="<your key>"`
  - Re‑run `pollux-config doctor` to confirm.

## Secrets appear missing in logs

- Symptom: Keys are printed as `***redacted***`.
- Explanation: Redaction is by design for safety. Use `pollux-config env` to confirm variables exist (still redacted), or rely on `pollux-config doctor` and application behavior.

## Python or import errors

- Symptom: `ModuleNotFoundError` or runtime errors on import.
- Fixes:
  - Use Python `3.13` and a clean virtual environment.
  - Install from Releases (wheel) or source with `pip install -e .`.

## Notebook visualization missing

- Symptom: Import errors for plotting in notebooks.
- Fix: Install visualization helpers:
  - `pip install "matplotlib~=3.10" "pandas~=2.3" "seaborn~=0.13"`

## Testing without an API key

If you want to verify your setup before making real API calls:

```bash
unset POLLUX_USE_REAL_API  # or export POLLUX_USE_REAL_API=0
```

In mock mode, outputs will look like `echo: <your prompt>`. This is useful for testing pipelines without incurring costs.

## Still stuck?

- Run `pollux-config doctor` and attach the output to any issue report.
- See [Configuration](configuration.md) for detailed setup or [CLI reference](../reference/cli.md) for diagnostic commands.
