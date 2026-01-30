# Remote File Materialization — How‑To

Audience: developers enabling PDF/remote URL promotion in the pipeline. Quadrant: How‑To (goal‑oriented).

Applies to: `ExecutionOptions.remote_files` and the Remote Materialization stage in the default executor pipeline.

Goal: Convert eligible remote HTTP(S) file references (e.g., arXiv/PDF URLs) into local files before execution, so the API handler can upload provider‑supported files.

## Steps

1. Enable the policy

```python title="enable_remote_files.py"
from pollux.core.execution_options import ExecutionOptions, RemoteFilePolicy

opts = ExecutionOptions(remote_files=RemoteFilePolicy(enabled=True))
```

2. Call a minimal run with an arXiv URL

```python title="run_with_remote.py"
import asyncio
from pollux import types, run_batch
from pollux.core.execution_options import ExecutionOptions, RemoteFilePolicy

async def main() -> None:
    opts = ExecutionOptions(remote_files=RemoteFilePolicy(enabled=True))
    res = await run_batch(
        prompts=["Summarize the paper"],
        sources=[types.Source.from_text("See: https://arxiv.org/abs/1234.56789")],
        options=opts,
    )
    print(res.get("status"))

asyncio.run(main())
```

3. Verification

- Expect `status` to be `ok`.
- With logging/telemetry enabled, check metrics for `remote.materialize` counters (see below).
- In debug runs, the plan should contain a `FilePlaceholder(ephemeral=True)` replacing a detected `FileRefPart`.

4. Troubleshooting

- HTTP rejected: Only HTTPS is allowed by default; set `allow_http=True` to permit plain HTTP.
- Size limit exceeded: Increase `max_bytes` or set `on_error='skip'` to leave parts unchanged.
- MIME detection: Use the `.pdf` extension heuristic or rely on Content‑Type when present.

Last reviewed: 2025-09

---

## Details

### Overview

- Purpose: Convert eligible remote HTTP(S) file references (e.g., arXiv/PDF URLs) into local files before execution so they can be uploaded using provider-supported file mechanisms.
- Scope: Purely client-side, provider-neutral. Runs as a dedicated pipeline stage before the API handler.
- Outcome: `FileRefPart` → `FilePlaceholder(ephemeral=True)` at the same index in shared and per‑call parts; the API handler uploads placeholders and replaces them with provider file references.

### When To Use

- You pass arXiv or other PDF URLs as sources or direct `FileRefPart`s.
- Your provider requires file uploads rather than external URLs for file content.
- You want predictable, explicit behavior with clear limits and telemetry.

### Quick Start

```python
from pollux.core.execution_options import ExecutionOptions, RemoteFilePolicy
from pollux import types
from pollux.frontdoor import run_batch

# Option A: quick enablement
opts = ExecutionOptions(remote_files=RemoteFilePolicy(enabled=True))

# Option B: via helper builder
# opts = make_execution_options(remote_files_enabled=True)

result = await run_batch(
    prompts=["Summarize the paper"],
    sources=[types.Source.from_text("See: https://arxiv.org/abs/1234.56789v2")],
    options=opts,
)
```

### Behavior

- Scope: scans `shared_parts` only or both `shared_parts` and each call’s `api_parts` depending on policy (`scope`).
- Security: HTTPS-only by default; set `allow_http=True` to permit plain HTTP.
- Detection: scans for HTTP(S) `FileRefPart`s:
  - MIME allowlist includes `application/pdf` by default.
  - Optional extension heuristic accepts URLs ending with `.pdf`.
  - arXiv `abs/<id>` links are canonicalized to `pdf/<id>.pdf`.
- Safety:
  - Bounded concurrency (`download_concurrency`).
  - Single‑flight per URI within a plan (the same URL downloads once).
  - Streaming download with `max_bytes`. urllib uses a single timeout; we use
    the maximum of `connect_timeout_s` and `read_timeout_s` as the effective timeout.
  - Optional `Content-Type` check when header is present.
- Replacement: matched parts become `FilePlaceholder(local_path, mime_type, ephemeral=True)` at the same index.
  - Upload and cleanup: the API handler uploads placeholders and unlinks ephemeral temp files after a successful upload.
  - Failure cleanup: if a later pipeline stage fails before upload, the executor
    performs a best‑effort cleanup of ephemeral placeholders found in the plan.

### Customization

`RemoteFilePolicy` fields and defaults:

- `enabled: bool = False` — master switch.
- `allowed_mime_types: tuple[str, ...] = ("application/pdf",)` — allowlist for detection.
- `allow_pdf_extension_heuristic: bool = True` — treat `*.pdf` URLs as PDFs when MIME is missing.
- `max_bytes: int = 25 * 1024 * 1024` — per‑download size cap (0 disables enforcement).
- `connect_timeout_s: float = 10.0` — connection timeout.
- `read_timeout_s: float = 30.0` — read timeout.
- `download_concurrency: int = 4` — max in‑flight downloads.
- `on_error: Literal['fail','skip'] = 'fail'` — fail the request or skip promotion on errors (e.g., size limit exceeded).
- `allow_http: bool = False` — allow plain HTTP (HTTPS-only by default).
- `scope: Literal['shared_only','shared_and_calls'] = 'shared_and_calls'` — control which parts are scanned.

### Examples

- Tighten limits and skip on oversize files:

```python
policy = RemoteFilePolicy(enabled=True, max_bytes=5 * 1024 * 1024, on_error="skip")
opts = ExecutionOptions(remote_files=policy)
```

- Require explicit MIME type; disable `.pdf` heuristic:

```python
policy = RemoteFilePolicy(enabled=True, allow_pdf_extension_heuristic=False)
```

### Telemetry

The stage emits gauges under the scope `remote.materialize`:

- `promoted_count`: number of replacements performed (shared + per‑call).
- `bytes_total`: total bytes downloaded.
- `skipped`: items skipped due to policy (e.g., on_error='skip').
- `errors`: hard errors (on_error='fail').
- `duration_s`: total stage duration.
- `uris_total`, `uris_unique`, `dedup_savings`: source URI counts and dedup gains.
- `download_concurrency`: effective policy concurrency value.

### Notes

- Ephemeral files: Placeholders produced by this stage are marked `ephemeral=True`; the API handler deletes their local temp files after successful upload.
- Provider neutrality: No SDK calls are made here; the API handler handles uploads via the configured adapter.
- Predictability: This is opt‑in and disabled by default. Enabling it does not affect caching behavior or token estimation.

### Troubleshooting

- HTTP rejected: By default, only HTTPS is allowed. Set `allow_http=True` in `RemoteFilePolicy` to permit plain HTTP.
- Redirected to non‑HTTP(S): If a server redirects to a non‑web scheme (e.g., `file://`), the stage rejects the URL for safety. Use a different source URI; non‑web schemes are not supported.
- Size limit exceeded: Increase `max_bytes` (bytes) if legitimate files exceed the default 25MB limit, or set `on_error='skip'` to leave parts unchanged instead of failing.
- Unknown Content‑Type: If the server does not return a PDF `Content-Type`, either rely on the `.pdf` extension heuristic or set `on_error='skip'`. When MIME is absent and a `.pdf` URL is used, a lightweight magic check verifies the `%PDF` header and rejects mismatches.
- Timeouts: Increase `connect_timeout_s` and/or `read_timeout_s` (the effective timeout is the larger of the two as used by `urllib`).
