# Troubleshooting

Fast fixes for common setup issues.

## Real API enabled but no key

**Symptom:** `pollux-config doctor` reports a missing `api_key`, or responses look like mock.

**Fix:**

```bash
export GEMINI_API_KEY="<your key>"
export POLLUX_USE_REAL_API=1
```

## Hitting rate limits immediately

**Symptom:** requests throttle right after enabling the real API.

**Fix:**

```bash
export POLLUX_TIER=free|tier_1|tier_2|tier_3
```

Then reduce concurrency in your config or per-call options if needed.

## Model/provider mismatch

**Symptom:** `Unknown model; provider defaulted to 'google'.`

**Fix:** use a valid model string for your provider (e.g., `gemini-2.0-flash`).

## Mock answers when expecting real results

**Symptom:** outputs look like `echo: ...` or include `mock` metadata.

**Fix:** ensure the real API is enabled and the key is present, then re-run:

```bash
pollux-config doctor
```

## Secrets appear missing in logs

**Symptom:** keys show as `***redacted***`.

**Explanation:** redaction is intentional. Use `pollux-config env` or
`pollux-config doctor` to confirm variables exist.

## Python or import errors

**Fixes:**

- Use Python `3.13` and a clean virtual environment.
- Install from releases (wheel) or source with `pip install -e .`.

## Still stuck?

- Run `pollux-config doctor` and attach the output to any issue report.
- See [CLI reference](../reference/cli.md) for diagnostic commands.
