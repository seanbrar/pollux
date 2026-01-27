# Provider Uploads (Extension)

Last reviewed: 2025-09

Goal: Pre‑upload a local file to the provider and wait until it becomes ACTIVE to avoid race conditions when generating immediately after upload.

When to use: You plan to reference a freshly uploaded media file (audio, image, PDF) in a generation right away and want to ensure it’s ready.

Prerequisites

- Python 3.13; repository installed (`make install-dev`).
- Real API key required for uploads (`GEMINI_API_KEY`), and optional runtime dependency on `google-genai`.
- Set `POLLUX_TIER` to match your billing to avoid throttling.

## 1) Quick start: get a file URI

```python title="preupload_quickstart.py"
from pollux.extensions.provider_uploads import preupload_and_wait_active

uri = preupload_and_wait_active(
    "./test_files/media/sample.mp3",  # local path
    timeout_s=60.0,                     # fail fast in 60s if not ACTIVE
)
print("Upload is ACTIVE at:", uri)

# Use `uri` in your request per provider semantics (e.g., as a file reference)
```

Success check

- The function returns a non‑empty `uri` when the file reaches `ACTIVE`.
- On timeout or failure, an exception is raised with details.

## 2) Core function with rich result

```python title="upload_with_result.py"
from pollux.extensions.provider_uploads import upload_and_wait_active

res = upload_and_wait_active(
    "./test_files/media/sample.mp3",
    timeout_s=90.0,
    cleanup_on_timeout=True,  # attempt delete if we time out
)
print(res.provider, res.id, res.uri, res.state)
assert res.state == "ACTIVE"
```

Notes

- Credentials precedence: explicit `api_key` arg > resolved project config > `GEMINI_API_KEY`.
- Polling uses exponential backoff with optional jitter and caps (see API reference for parameters).
- Terminal failure states raise `UploadFailedError`; timeouts raise `UploadInactiveError`.

Troubleshooting

- Missing key: set `GEMINI_API_KEY` and re‑run. Use `pollux-config doctor` to verify readiness.
- SDK not installed: install `google-genai` (see error message) or vendor‑lock to local mocks for tests.
- Rate limits: reduce concurrent uploads; increase `timeout_s`/backoff; match `POLLUX_TIER` to billing.

See also

- API Reference: [Provider Uploads](../reference/api/extensions/provider-uploads.md)
- Related: [Remote File Materialization](remote-file-materialization.md)
