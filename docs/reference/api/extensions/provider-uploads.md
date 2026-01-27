# Provider Uploads — API

Status: Experimental

Purpose: Pre-upload local files to the provider and wait for the `ACTIVE` state. This reduces race conditions when issuing a generation immediately after upload.

## Functions

- `preupload_and_wait_active(path, *, provider='google', timeout_s=120.0, poll_s=2.0, max_poll_s=10.0, backoff_factor=1.5, jitter_s=0.2, cleanup_on_timeout=False, api_key=None) -> str`
  - Convenience wrapper returning the file URI.

- `upload_and_wait_active(path, *, provider='google', timeout_s=120.0, poll_s=2.0, max_poll_s=10.0, backoff_factor=1.5, jitter_s=0.2, cleanup_on_timeout=False, api_key=None) -> UploadResult`
  - Core function returning `UploadResult` with `provider`, `id`, `uri`, and final `state`.

### Behavior

- Validates the local file path and provider support.
- Uploads the file via the provider SDK (`google-genai`) and polls for state.
- Polling uses exponential backoff with a minimum delay of 0.01s and optional jitter.
- On terminal failure states (`FAILED`, `ERROR`, `CANCELLED`), raises `UploadFailedError`. If `cleanup_on_timeout=True`, attempts to delete the uploaded file before raising.
- On timeout, raises `UploadInactiveError`. If `cleanup_on_timeout=True`, attempts to delete the uploaded file before raising.
- Credentials precedence: explicit `api_key` arg > resolved project config > `GEMINI_API_KEY`.

## Types & Exceptions

- `UploadResult`: dataclass with fields: `provider: str`, `id: str`, `uri: str`, `state: str`.
- `UploadInactiveError`: the file did not become `ACTIVE` within the timeout.
- `UploadFailedError`: provider reported a terminal failure state. Attributes: `provider`, `state`, `details`.
- `MissingCredentialsError`: credentials not available in config or environment.
- `MissingDependencyError`: optional `google-genai` SDK not installed.

## Example

```python
from pollux.extensions.provider_uploads import preupload_and_wait_active

uri = preupload_and_wait_active("/path/to/sample.mp3", timeout_s=60)
# Use `uri` or the returned object from `upload_and_wait_active` in your request
```

Notes:

- This extension is a stop-gap for richer handling in the core library.
- For remote URLs, see the Remote File Materialization stage: `how-to/remote-file-materialization.md`.
