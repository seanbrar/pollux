# Troubleshooting

Fast fixes for common setup issues.

## Use this page when

- setup succeeds partially but requests fail
- output behavior is different from what you expect
- provider/model/input combinations fail with configuration or API errors

## Before you debug

- confirm your provider/model pairing is intentional
- confirm `use_mock` matches your expectation
- reduce to a minimal `run()` call before scaling complexity

## Missing API key

**Fix:**

```bash
export GEMINI_API_KEY="<your key>"
export OPENAI_API_KEY="<your key>"
```

Or pass `api_key` explicitly in `Config(...)`.

## Unexpected mock responses

**Symptom:** outputs look like `echo: ...`.

**Fix:** ensure `use_mock=False` (default) and key is present.

## Provider/model mismatch

**Symptom:** configuration or API errors right at request time.

**Fix:** verify the model belongs to the selected provider.

## Option not implemented in v1.0

**Symptom:** `ConfigurationError` for:

- `delivery_mode="deferred"`
- `history`
- `continue_from`

**Explanation:** these are intentionally reserved/disabled in v1.0.

## OpenAI multimodal limitations

**Symptom:** remote source rejected with unsupported type.

**Explanation (v1.0):** OpenAI remote URL support is explicit:

- PDFs via `input_file.file_url`
- Images via `input_image.image_url`

Other remote MIME types are rejected by design.

## Secrets appear missing in logs

**Symptom:** keys show as `***redacted***`.

**Explanation:** redaction is intentional.

## Python or import errors

**Fixes:**

- Use a supported Python version (`>=3.10,<3.15`; 3.13 is common in local dev) and a clean virtual environment.
- Install from releases (wheel) or source with `pip install -e .`.
- Run:
  - `make test`
  - `make lint`
  - `make typecheck`

## Still stuck?

- Include:
  - provider + model
  - source type(s)
  - exact exception message
- See [Provider Capabilities](../reference/provider-capabilities.md).
- Open an issue with concrete repro details:
  - [Bug report template](https://github.com/seanbrar/pollux/issues/new?template=bug.md)
  - [Feature request template](https://github.com/seanbrar/pollux/issues/new?template=feature.md)
