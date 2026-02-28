<!-- Intent: Teach error handling for Pollux pipelines: the exception
     hierarchy, failure triage, production error patterns (category-specific
     catching, circuit breakers, partial failures, resume-on-failure). Do NOT
     re-explain tool calling or conversation mechanics. Assumes the reader has
     used run() and understands Config/Options. Register: reference + guided
     applied (patterns). -->

# Handling Errors and Recovery

You want your Pollux-based pipeline to handle failures gracefully. Retry
what's transient, skip what's broken, and log enough to diagnose issues
later.

At the API level, LLM provider calls can fail for many reasons: invalid
credentials, rate limits, malformed input, server errors, unsupported
feature combinations. An orchestration layer needs a structured way to
surface these failures so your code can make informed recovery decisions
without parsing error strings.

## Exception Hierarchy

Pollux uses a single exception hierarchy rooted at `PolluxError`:

```
PolluxError
├── ConfigurationError   # Bad config, missing key, unsupported feature
├── SourceError          # File not found, invalid arXiv reference
├── PlanningError        # Execution plan could not be built
├── InternalError        # Bug or invariant violation inside Pollux
└── APIError             # Provider call failed
    ├── RateLimitError   # HTTP 429 (always retryable)
    └── CacheError       # Cache operation failed
```

Every error carries a `.hint` attribute with actionable guidance:

```python
from pollux import Config, ConfigurationError

try:
    config = Config(provider="gemini", model="gemini-2.5-flash-lite")
except ConfigurationError as e:
    print(e)       # "API key required for gemini"
    print(e.hint)  # "Set GEMINI_API_KEY environment variable or pass api_key=..."
```

This lets calling code display helpful messages without parsing exception
strings.

!!! info "Boundary"
    **Pollux owns:** retrying transient API failures (rate limits, server
    errors) within a single `run()` or `run_many()` call, respecting
    `Retry-After` headers, and raising typed exceptions with `.hint`.

    **You own:** workflow-level retry decisions (should I retry this file?),
    error categorization for your logging/alerting, partial-failure policies
    (skip vs abort), and circuit-breaking across calls.

## Failure Triage

Use this order when debugging. Most failures resolve by step 2.

1. **Auth and mode check.** Is `use_mock` what you expect? For real mode,
   ensure the matching key exists (`GEMINI_API_KEY` or `OPENAI_API_KEY`).

2. **Provider/model pairing.** Verify the model belongs to the selected
   provider. Re-run a minimal prompt after fixing any mismatch.

3. **Unsupported feature.** Compare your options against
   [Provider Capabilities](reference/provider-capabilities.md).
   `delivery_mode="deferred"` is not supported. Conversation continuity
   and tool calling are supported by both Gemini and OpenAI.

4. **Source and payload.** Reduce to one source + one prompt and retry.
   For OpenAI remote URLs, only PDF and image URLs are supported.

## Complete Production Example

A production wrapper that processes files with category-specific error
handling, structured logging, and a summary report:

```python
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

from pollux import (
    APIError,
    Config,
    ConfigurationError,
    PolluxError,
    RateLimitError,
    Source,
    SourceError,
    run,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

config = Config(provider="gemini", model="gemini-2.5-flash-lite")


@dataclass
class RunReport:
    succeeded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        total = len(self.succeeded) + len(self.skipped) + len(self.failed)
        return (
            f"{total} files: {len(self.succeeded)} ok, "
            f"{len(self.skipped)} skipped, {len(self.failed)} failed"
        )


async def safe_analyze(path: Path, prompt: str) -> str | None:
    """Analyze a file with category-specific error handling."""
    try:
        result = await run(
            prompt,
            source=Source.from_file(str(path)),
            config=config,
        )
        if result["status"] == "partial":
            log.warning("%s: partial result (some answers empty)", path.name)
        return result["answers"][0]

    except ConfigurationError as exc:
        # Bad config — nothing to retry, abort early
        log.error("Configuration error: %s (hint: %s)", exc, exc.hint)
        raise  # Let the caller abort the pipeline

    except SourceError as exc:
        # Bad input file — skip it, process the rest
        log.warning("Skipping %s: %s (hint: %s)", path.name, exc, exc.hint)
        return None

    except RateLimitError as exc:
        # Pollux already retried; we're still rate-limited
        log.warning(
            "Rate limit on %s after retries (hint: %s)", path.name, exc.hint
        )
        return None

    except APIError as exc:
        # Other provider errors — log details for diagnosis
        log.error(
            "API error on %s: %s [status=%s, retryable=%s] (hint: %s)",
            path.name, exc, exc.status_code, exc.retryable, exc.hint,
        )
        return None

    except PolluxError as exc:
        # Catch-all for unexpected Pollux errors
        log.error("Unexpected error on %s: %s (hint: %s)", path.name, exc, exc.hint)
        return None


async def process_collection(directory: str, prompt: str) -> RunReport:
    """Process all PDFs with error tracking."""
    report = RunReport()

    for path in sorted(Path(directory).glob("*.pdf")):
        answer = await safe_analyze(path, prompt)
        if answer is not None:
            report.succeeded.append(path.name)
        else:
            report.skipped.append(path.name)

    log.info(report.summary())
    return report


asyncio.run(process_collection("./papers", "Summarize the key findings."))
```

### Step-by-Step Walkthrough

1. **Catch by category, not by message.** The exception hierarchy lets you
   handle `ConfigurationError`, `SourceError`, `RateLimitError`, and
   `APIError` differently without parsing error strings.

2. **Use `.hint` for logging.** Every Pollux exception has a `.hint` with
   actionable guidance. Log it alongside the error message for faster
   diagnosis.

3. **Abort on configuration errors.** `ConfigurationError` means the setup
   is wrong (missing API key, unsupported feature). Retrying won't help.
   Re-raise to abort the pipeline.

4. **Skip on source errors.** `SourceError` means a specific input is bad
   (file not found, unreadable format). Skip the file and continue.

5. **Log and continue on API errors.** `APIError` and `RateLimitError` mean
   Pollux already retried internally. At the workflow level, log the failure
   and move on. Consider a workflow-level retry for important files.

## Common Symptoms and Fixes

| Symptom | Likely Cause | Fix |
|---|---|---|
| `ConfigurationError` at startup | Missing API key | `export GEMINI_API_KEY="your-key"` or pass `api_key` in `Config(...)` |
| Outputs look like `echo: ...` | `use_mock=True` is set | Set `use_mock=False` (default) and ensure the API key is present |
| `ConfigurationError` at request time | Provider/model mismatch | Verify the model belongs to the selected provider |
| `ConfigurationError` mentioning `delivery_mode` | `"deferred"` is not supported | Use `delivery_mode="realtime"` (default) |
| `status: "partial"` | Some prompts returned empty answers | Check individual entries in `answers` to identify which prompts failed |
| Remote source rejected | Unsupported MIME type on OpenAI | OpenAI remote URL support is limited to PDFs and images |
| Keys show as `***redacted***` | Intentional redaction | Your key is still being used. `Config` hides it from string representations |
| Import errors | Missing dependencies | Use Python `>=3.10,<3.15` with `uv sync --all-extras` |

## Variations

### Using `.hint` for observability

The `.hint` attribute is designed for human-readable context. Include it in
structured logs, alerts, or error dashboards:

```python
except PolluxError as exc:
    log.error(
        "pollux_error",
        extra={
            "error_type": type(exc).__name__,
            "message": str(exc),
            "hint": exc.hint,
            "file": path.name,
        },
    )
```

For `APIError` subclasses, additional attributes provide structured metadata:

```python
except APIError as exc:
    log.error(
        "api_error",
        extra={
            "status_code": exc.status_code,
            "retryable": exc.retryable,
            "provider": exc.provider,
            "retry_after_s": exc.retry_after_s,
        },
    )
```

### Circuit breaker

Stop processing when errors pile up. Consecutive failures usually mean
a systemic issue, not isolated bad files:

```python
MAX_CONSECUTIVE_FAILURES = 3

async def process_with_circuit_breaker(
    directory: str, prompt: str,
) -> RunReport:
    report = RunReport()
    consecutive_failures = 0

    for path in sorted(Path(directory).glob("*.pdf")):
        answer = await safe_analyze(path, prompt)

        if answer is not None:
            report.succeeded.append(path.name)
            consecutive_failures = 0
        else:
            report.skipped.append(path.name)
            consecutive_failures += 1

        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            log.error("Circuit breaker: %d consecutive failures, aborting", consecutive_failures)
            break

    return report
```

### Distinguishing `status: "partial"` from exceptions

Not all problems are exceptions. A `status: "partial"` result means some
prompts in a `run_many()` call returned empty answers. The call succeeded
but the output is incomplete:

```python
result = await run_many(prompts, sources=sources, config=config)

if result["status"] == "ok":
    # All answers populated — process normally
    pass
elif result["status"] == "partial":
    # Some answers are empty strings — decide per-answer
    for i, answer in enumerate(result["answers"]):
        if answer:
            process_answer(i, answer)
        else:
            log.warning("Empty answer for prompt %d", i)
elif result["status"] == "error":
    # All answers empty — treat as a failure
    log.error("All answers empty")
```

### Durable Pipelines with Resume-on-Failure

For long-running jobs where partial failures are expected, persist a
manifest that tracks per-item status. Retries then process only unfinished
or failed items:

```json
{
  "items": {
    "input.txt": {"status": "ok", "output": "outputs/items/input.json"},
    "compare.txt": {"status": "error", "error": "RateLimitError: 429"},
    "notes.txt": {"status": "pending"}
  }
}
```

On retry, items with `status: "ok"` are skipped. The manifest updates after
each item (not only at run end), so you never lose progress. See the
`resume-on-failure` cookbook recipe for a runnable implementation:

```bash
python -m cookbook production/resume-on-failure \
  --input cookbook/data/demo/text-medium --limit 4 \
  --manifest outputs/manifest.json --output-dir outputs/items --mock
```

## What to Watch For

- **Pollux retries internally; you retry at the workflow level.** Don't
  wrap `run()` in a retry loop for transient errors. `RetryPolicy` already
  handles that. Your retries are for workflow-level decisions.
- **`ConfigurationError` is never transient.** Missing API keys, unsupported
  features, invalid config. These won't fix themselves. Abort and fix the
  config.
- **`RateLimitError` means retries were exhausted.** Pollux already waited
  and retried. If you still get `RateLimitError`, reduce concurrency or add
  a longer backoff at the workflow level.
- **Check `result["status"]` even on success.** A successful call can return
  `"partial"` status with some empty answers. Don't assume all answers are
  populated because no exception was raised.
- **Don't catch `Exception` when you mean `PolluxError`.** Catching too
  broadly hides bugs in your own code. Catch `PolluxError` for
  Pollux-specific failures; let everything else propagate.

---

For the full configuration reference (including `RetryPolicy` fields, mock
mode, and API key resolution), see [Configuring Pollux](configuration.md).

## Still Stuck?

Include the following in your bug report:

- Provider + model
- Source type(s)
- Exact exception message

[File a bug report](https://github.com/seanbrar/pollux/issues/new?template=bug.md)
with concrete reproduction steps.
