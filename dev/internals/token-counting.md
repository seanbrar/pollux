# Token Counting (Extension)

This page shows how to use the token‑counting extension to get a token count for text either via:

- The real Google Gemini tokenizer (when `google-genai` is installed), or
- A fast, SDK‑free fallback estimation.

The extension is provider‑aware but remains a good architectural citizen: it uses **validated inputs** and **union result types** for structural robustness, and it never leaks SDK calls into the core pipeline.

## Quick Start

```python
import asyncio
from pollux.extensions import (
    GeminiTokenCounter,
    ValidContent,
    TokenCountSuccess,
    TokenCountFailure,
)

async def main() -> None:
    text = "Hello, token counting!"
    content = ValidContent.from_text(text)

    # Fallback estimation (no SDK required)
    counter = GeminiTokenCounter(use_fallback_estimation=True)
    result = await counter.count_tokens(content)

    match result:
        case TokenCountSuccess(count=c, metadata=m):
            print(f"Tokens: {c} (method={m['counting_method']})")
        case TokenCountFailure(error=e):
            print(f"Failed: {e.error_type}: {e.message}")

asyncio.run(main())
```

## Using the real Gemini tokenizer

Install the SDK:

```bash
pip install google-genai
```

Then call with `use_fallback_estimation=False` (default):

```python
counter = GeminiTokenCounter()  # uses real tokenizer if SDK is available
result = await counter.count_tokens(ValidContent.from_text("..."), model_name="gemini-2.0-flash")
```

The extension initializes a minimal `genai.Client()` without API key (Gemini’s token counting endpoint is free). If the SDK is unavailable or the call fails, the error is surfaced in a structured `TokenCountFailure` with a recovery hint.

## Result shape

Results are **structurally sound** (mutually exclusive success/failure):

- `TokenCountSuccess`: `count`, `content_type`, `char_count`, `metadata` (includes `counting_method`, `base_count`, `model_name`).
- `TokenCountFailure`: `error` (message/type/hint), `metadata`.

This makes invalid states (e.g., “success with error”) impossible at the type level and keeps mypy strictness clean.

## Hints (optional)

You can pass planner‑style estimation hints to conservatively widen/clamp counts:

```python
from pollux.core.execution_options import EstimationOptions

hints = (EstimationOptions(widen_max_factor=1.2, clamp_max_tokens=10000),)
await counter.count_tokens(ValidContent.from_text("..."), hints=hints)
```

Hints are applied purely on the result of the base count; they never call provider SDKs.

## Notes

- The extension lives under `pollux.extensions.token_counting` and is exported via `pollux.extensions` for convenience.
- The API is intentionally small and uses validated construction (`ValidContent.from_text`) to prevent invalid inputs.
- This extension is independent from the conversation/pipeline flow; it’s a self‑contained utility.

## Budgeting example (estimate conservatively)

Estimate a token budget with a safety margin before issuing a batch.

```python title="budget_tokens.py"
import asyncio
from pollux.extensions import GeminiTokenCounter, ValidContent, TokenCountSuccess

async def main() -> None:
    text = "Long input ..."
    counter = GeminiTokenCounter(use_fallback_estimation=True)
    res = await counter.count_tokens(ValidContent.from_text(text), model_name="gemini-2.0-flash")
    est = 0
    if isinstance(res, TokenCountSuccess):
        # Base estimate
        est = res.count
    # Apply a conservative margin (20% over)
    budget = int(est * 1.2) if est else 2048  # default fallback
    print({"estimate": est, "budget": budget})

asyncio.run(main())
```

Notes:

- Real counts can vary by provider/model. Treat estimates as guidance and add a safety factor.
- For stricter bounds, pass `EstimationOptions` to widen/clamp ranges before deciding.

## See also

- Explanation → Deep Dives → [Token Counting Calibration](../explanation/deep-dives/token-counting-calibration.md): methodology, findings, and validation targets.
- Decisions → [ADR‑0002 — Token Counting Model](../explanation/decisions/ADR-0002-token-counting-model.md): architecture and policies for estimation vs. validation.
