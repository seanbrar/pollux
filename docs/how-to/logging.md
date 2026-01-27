# Logging

Configure logging in your application to see detailed logs from `pollux` when you need them. The library never configures handlers for you; it only attaches a `NullHandler` to avoid warnings. You are in full control.

## Quick start

```python
import logging

# 1) Configure handlers/formatting in YOUR app
logging.basicConfig(
    level=logging.INFO,  # change to DEBUG for deep dives
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)

# 2) Adjust verbosity per module namespace
logging.getLogger("pollux").setLevel(logging.WARNING)  # quiet by default
logging.getLogger("pollux.executor").setLevel(logging.INFO)
# For deep debugging of a specific component:
# logging.getLogger("pollux.pipeline.api_handler").setLevel(logging.DEBUG)
```

## Verification

- Run a small script that imports `pollux` and triggers a single operation (e.g., `run_simple`).
- Expect INFO lines from your root logger and any module loggers you set to INFO/DEBUG.
- Programmatic check: `assert logging.getLogger("pollux").getEffectiveLevel() <= logging.INFO`.

## Best practices

- Be explicit: configure logging in your app or entry script; the library won’t add handlers.
- Use hierarchical control: set a broad level for `pollux`, then override specific submodules as needed.
- Include exception context with `log.exception(...)` or `exc_info=True` for actionable traces.
- Avoid sensitive data in logs: do not log API keys or raw private content.

## Common setups

Console only (development):

```python
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
logging.getLogger("pollux").setLevel(logging.INFO)
```

File + console (production-friendly):

```python
logger = logging.getLogger()
logger.setLevel(logging.INFO)

fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s")

console = logging.StreamHandler()
console.setFormatter(fmt)
logger.addHandler(console)

fileh = logging.FileHandler("app.log")
fileh.setFormatter(fmt)
logger.addHandler(fileh)

# Reduce noise globally, then opt-in per module
logging.getLogger("pollux").setLevel(logging.WARNING)
```

## Notes

- The library’s root logger installs `logging.NullHandler()` to avoid “No handler found” warnings; your handlers take precedence when configured.
- See Troubleshooting for reading typical messages and next actions.

## Troubleshooting

- I don’t see logs: Ensure you configured handlers (e.g., `basicConfig`) and that the effective level allows the messages you expect.
- Too noisy: Reduce the `pollux` namespace to `WARNING` and enable INFO/DEBUG only on specific submodules.

Last reviewed: 2025-09
