# Troubleshooting

Fast fixes for common setup and runtime issues.

## Before You Debug

- Confirm your provider/model pairing is intentional.
- Confirm `use_mock` matches your expectation.
- Reduce to a minimal `run()` call before scaling complexity.

## Common Error Types

| Error | Meaning |
|---|---|
| `ConfigurationError` | Bad config, missing API key, or unsupported feature for the selected provider |
| `SourceError` | File not found, invalid arXiv reference, or malformed source input |
| `PlanningError` | Execution plan could not be built from the given request |
| `InternalError` | A bug or invariant violation inside Pollux — please report it |
| `APIError` | Provider call failed (check `.retryable` and `.status_code`) |
| `RateLimitError` | HTTP 429 — always retryable; Pollux auto-retries per `RetryPolicy` |
| `CacheError` | Cache creation or lookup failed |

All Pollux errors carry a `.hint` attribute with actionable guidance. Check
`e.hint` before searching for solutions.

## Failure Triage

Use this order — most failures resolve by step 2.

1. **Auth and mode check** — Is `use_mock` what you expect? For real mode,
   ensure the matching key exists (`GEMINI_API_KEY` or `OPENAI_API_KEY`).

2. **Provider/model pairing** — Verify the model belongs to the selected
   provider. Re-run a minimal prompt after fixing any mismatch.

3. **Unsupported feature** — Compare your options against
   [Provider Capabilities](reference/provider-capabilities.md).
   `delivery_mode="deferred"` is reserved; conversation continuity is
   provider-dependent (OpenAI-only in v1.1).

4. **Source and payload** — Reduce to one source + one prompt and retry.
   For OpenAI remote URLs in v1.0, only PDF and image URLs are supported.

## Missing API Key

```bash
export GEMINI_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

Or pass `api_key` directly in `Config(...)`.

## Unexpected Mock Responses

**Symptom:** outputs look like `echo: ...`.

**Fix:** ensure `use_mock=False` (default) and the API key is present.

## Provider/Model Mismatch

**Symptom:** `ConfigurationError` or `APIError` at request time.

**Fix:** verify the model belongs to the selected provider.

## Option Not Implemented Yet

**Symptom:** `ConfigurationError` mentioning `delivery_mode="deferred"`,
`history`, or `continue_from`.

`delivery_mode="deferred"` is intentionally reserved.
`history`/`continue_from` require a provider with conversation support.

## `status == "partial"`

**Symptom:** the envelope returns `status: "partial"` instead of `"ok"`.

This means some prompts returned empty answers while others succeeded. Common
causes: a prompt that the model can't answer from the provided source, or a
transient provider error on one of several concurrent calls. Check individual
entries in `answers` to identify which prompts failed.

## OpenAI Multimodal Limitations

**Symptom:** remote source rejected with unsupported type.

In v1.0, OpenAI remote URL support is limited to PDFs and images. Other
remote MIME types are rejected by design.

## Secrets Appear Missing in Logs

**Symptom:** keys show as `***redacted***`.

Redaction is intentional. Your key is still being used — `Config` just hides
it from string representations.

## Python or Import Errors

- Use a supported Python version (`>=3.10,<3.15`; 3.13 recommended) with a
  clean virtual environment.
- Install dev dependencies: `uv sync --all-extras` (or `pip install -e .` for the library only).
- Run `make check` to verify the full setup.

## Still Stuck?

Include the following in your bug report:

- Provider + model
- Source type(s)
- Exact exception message

[File a bug report](https://github.com/seanbrar/pollux/issues/new?template=bug.md)
with concrete reproduction steps.
