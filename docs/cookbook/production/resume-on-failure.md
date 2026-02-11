# Resume on Failure

Persist a manifest so retries process only unfinished or failed items. This
is the durability pattern for long-running jobs where partial failures are
expected.

## How It Works

The recipe maintains a JSON manifest that tracks per-item status:

```json
{
  "items": {
    "input.txt": {"status": "ok", "output": "outputs/items/input.json"},
    "compare.txt": {"status": "error", "error": "RateLimitError: 429"},
    "notes.txt": {"status": "pending"}
  }
}
```

On retry with `--failed-only`, items with `status: "ok"` are skipped.

## Run It

Initial run:

```bash
python -m cookbook production/resume-on-failure \
  --input cookbook/data/demo/text-medium --limit 4 \
  --manifest outputs/manifest.json --output-dir outputs/items --mock
```

Retry only failed/pending items:

```bash
python -m cookbook production/resume-on-failure \
  --input cookbook/data/demo/text-medium --failed-only \
  --manifest outputs/manifest.json --output-dir outputs/items --mock
```

## What You'll See

Initial run:

```
Processing 4 items...
  input.txt: ok
  compare.txt: ok
  notes.txt: error (simulated)
  extra.txt: ok

Manifest: 3 ok, 1 error → outputs/manifest.json
```

Retry run:

```
Resuming: 1 item pending/failed
  notes.txt: ok

Manifest: 4 ok, 0 error → outputs/manifest.json
```

The manifest updates after each item (not only at run end). Per-item JSON
artifacts in `--output-dir` preserve answers, usage, and metrics.

## Tuning

- `--max-retries` and `--backoff-seconds` control retry aggressiveness.
- `--limit` sets workload size for staged production rollout.
- Use a stable input directory between retries — changing item identity
  breaks resumability.

## Next Steps

Split retries by error category (rate-limit vs validation) for smarter
retry logic. Export manifest rollups to dashboards for operational visibility.
