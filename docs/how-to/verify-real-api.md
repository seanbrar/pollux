# Verify Real API — Success Checks

> Goal: Prove you are running against the real provider, not mock mode, and avoid rate‑limit surprises.
>
> Prerequisites: Quickstart completed in mock mode.

## 1) Enable real calls

<!-- markdownlint-disable MD046 -->
=== "Bash/Zsh"

    ```bash
    export GEMINI_API_KEY="<your key>"
    export POLLUX_TIER=free      # free | tier_1 | tier_2 | tier_3
    export POLLUX_USE_REAL_API=1

    # Sanity check (redacted)
    pollux-config doctor
    ```

=== "PowerShell"

    ```powershell
    $Env:GEMINI_API_KEY = "<your key>"
    $Env:POLLUX_TIER = "free"
    $Env:POLLUX_USE_REAL_API = "1"
    pollux-config doctor
    ```
<!-- markdownlint-enable MD046 -->

## 2) Programmatic check

Confirm configuration from Python:

```python
from pollux.config import resolve_config
cfg = resolve_config()
print(cfg.use_real_api, cfg.tier, cfg.model)
# expect: True free gemini-2.0-flash   (tier may differ)
```

## 3) Runtime signal (simple)

Re-run your Quickstart script and ensure the answer does not include the `echo:` prefix used by mock mode.

```text
# expected: a non‑echo model response
```

## 4) Runtime signal (explicit, optional)

Enable the raw preview to attach a compact provider preview into the result envelope.

```bash
export POLLUX_TELEMETRY_RAW_PREVIEW=1
```

Then inspect the envelope:

```python
from pollux import run_simple, types

res = await run_simple("Check", source=types.Source.from_text("X"))
preview = res["metrics"].get("raw_preview")
print(bool(preview))  # expect: True with real API when raw preview is enabled
```

Notes:

- Raw preview is independent of general telemetry and sanitized by design.
- If preview is missing, verify `POLLUX_TELEMETRY_RAW_PREVIEW=1` and that you are not in mock mode.

Alternative (no env var): pass `include_raw_preview=True` to the API handler.

```python
from pollux.pipeline.api_handler import APIHandler
handler = APIHandler(include_raw_preview=True)
# use in your pipeline; preview will be attached under metrics.raw_preview
```

## 5) If throttled

- Ensure `POLLUX_TIER` matches your billing plan.
- Reduce concurrency: set `request_concurrency=1` via config or per‑call options.
- See How‑to → Troubleshooting for details.

Last reviewed: 2025-09
