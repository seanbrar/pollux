# Provider Capabilities

This page defines the v1.2 capability contract by provider.

Pollux is **capability-transparent**, not capability-equalizing: providers are allowed to differ, and those differences are surfaced clearly.

## Policy

- Provider feature parity is **not** required for release.
- Unsupported features must fail fast with actionable errors.
- New provider features do not require immediate cross-provider implementation.

## Capability Matrix (v1.2)

| Capability | Gemini | OpenAI | Anthropic | Notes |
|---|---|---|---|---|
| Text generation | ✅ | ✅ | ✅ | Core feature |
| Multi-prompt execution (`run_many`) | ✅ | ✅ | ✅ | One call per prompt, shared context |
| Local file inputs | ✅ | ✅ | ❌ | OpenAI uses Files API upload; Anthropic supports URL inputs only |
| PDF URL inputs | ✅ (via URI part) | ✅ (native `input_file.file_url`) | ✅ (native `document` URL block) | |
| Image URL inputs | ✅ (via URI part) | ✅ (native `input_image.image_url`) | ✅ (native `image` URL block) | |
| YouTube URL inputs | ✅ | ⚠️ limited | ⚠️ limited | OpenAI/Anthropic parity layers (download/re-upload) are out of scope |
| Provider-side context caching | ✅ | ❌ | ❌ | OpenAI and Anthropic providers return unsupported for caching |
| Structured outputs (`response_schema`) | ✅ | ✅ | ✅ | JSON-schema path in all providers |
| Reasoning controls (`reasoning_effort`) | ✅ | ✅ | ✅ | Passed through to provider; see notes below |
| Deferred delivery (`delivery_mode="deferred"`) | ❌ | ❌ | ❌ | Not supported; raises `ConfigurationError` |
| Tool calling | ✅ | ✅ | ✅ | Tool definitions via `Options.tools`; results in `ResultEnvelope.tool_calls` |
| Tool message pass-through in history | ✅ | ✅ | ✅ | Provider-native tool call/result encoding |
| Conversation continuity (`history`, `continue_from`) | ✅ | ✅ | ✅ | Single prompt per call; supports tool messages in history |

## Provider-Specific Notes

### Gemini

- Context caching uses the Gemini Files API and `cachedContents`.
- Conversation history is translated to `Content` objects with
  `Part.from_function_call` / `Part.from_function_response` for tool turns.
- Gemini does not support `previous_response_id`; conversation state is
  carried entirely via `history`.
- Tool parameter schemas are normalized at the provider boundary:
  `additionalProperties` is stripped because the Gemini API rejects it.
- Reasoning: `reasoning_effort` maps to `ThinkingConfig(thinking_level=...)`.
  Full thinking text is returned in `ResultEnvelope.reasoning`. This maps
  cleanly on Gemini 3 models (for example `gemini-3-flash-preview`). Gemini
  2.x models use a different control (`thinking_budget`) and will return a
  provider error if `reasoning_effort` is set.

### OpenAI

- File uploads use `purpose="user_data"` with finite `expires_after` metadata.
  Pollux performs best-effort cleanup of uploaded files after execution.
- Remote URL support is intentionally narrow: PDFs and images only.
- Conversation can use either explicit `history` or `previous_response_id`
  (via `continue_from`). When `previous_response_id` is set, only tool
  result messages are forwarded from history; the rest is handled
  server-side by OpenAI.
- Sampling controls are model-specific: GPT-5 family models currently reject
  `temperature` and `top_p`, while older models (for example `gpt-4.1-nano`)
  accept them.
- Tool parameter schemas are normalized for strict mode: `additionalProperties:
  false` and `required` are injected automatically. Callers who set `strict:
  false` on a tool definition bypass normalization.
- Reasoning: `reasoning_effort` maps to `reasoning.effort` with automatic
  `summary: "auto"` to request reasoning summaries. Summaries appear in
  `ResultEnvelope.reasoning`; raw reasoning traces are not exposed by OpenAI.
  Reasoning token counts may appear in `ResultEnvelope.usage["reasoning_tokens"]`
  when OpenAI returns them. Some older models reject `reasoning.effort`.

### Anthropic

- Remote URL support is intentionally narrow: images and PDFs only.
- Reasoning: `reasoning_effort` maps to `output_config.effort`.
  Pollux uses `thinking.type="adaptive"` on adaptive-capable models
  (currently Opus 4.6) and falls back to manual thinking budgets on older
  models.
- Thinking block replay: when Anthropic returns `thinking` or
  `redacted_thinking` blocks, Pollux preserves them in conversation state and
  replays them verbatim on continuation turns so tool loops remain valid.

## Error Semantics

When a requested feature is unsupported for the selected provider or release scope, Pollux raises `ConfigurationError` or `APIError` with a concrete hint, instead of degrading silently.

For example, enabling caching with OpenAI:

```python
from pollux import Config

config = Config(
    provider="openai",
    model="gpt-5-nano",
    enable_caching=True,  # not supported for OpenAI
)
# At execution time, Pollux raises:
# ConfigurationError: Provider does not support caching
# hint: "Disable caching or choose a provider with caching support."
```

The error is raised at execution time (not at `Config` creation) because
caching support is a provider capability checked during plan execution.
