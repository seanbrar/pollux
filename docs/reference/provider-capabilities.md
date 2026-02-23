# Provider Capabilities

This page defines the v1.2 capability contract by provider.

Pollux is **capability-transparent**, not capability-equalizing: providers are allowed to differ, and those differences are surfaced clearly.

## Policy

- Provider feature parity is **not** required for release.
- Unsupported features must fail fast with clear errors.
- New provider features do not require immediate cross-provider implementation.

## Capability Matrix (v1.2)

| Capability | Gemini | OpenAI | Notes |
|---|---|---|---|
| Text generation | ✅ | ✅ | Core feature |
| Multi-prompt execution (`run_many`) | ✅ | ✅ | One call per prompt, shared context |
| Local file inputs | ✅ | ✅ | OpenAI uses Files API upload |
| PDF URL inputs | ✅ (via URI part) | ✅ (native `input_file.file_url`) | |
| Image URL inputs | ✅ (via URI part) | ✅ (native `input_image.image_url`) | |
| YouTube URL inputs | ✅ | ⚠️ limited | OpenAI parity layer (download/re-upload) is out of scope |
| Provider-side context caching | ✅ | ❌ | OpenAI provider returns unsupported for caching |
| Structured outputs (`response_schema`) | ✅ | ✅ | JSON-schema path in both providers |
| Reasoning controls (`reasoning_effort`) | ✅ | ✅ | Passed through to provider; see notes below |
| Deferred delivery (`delivery_mode="deferred"`) | ❌ | ❌ | Explicitly disabled |
| Tool calling | ✅ | ✅ | Tool definitions via `Options.tools`; results in `ResultEnvelope.tool_calls` |
| Tool message pass-through in history | ✅ | ✅ | Gemini maps to `Content`/`Part` types; OpenAI maps to `function_call`/`function_call_output` |
| Conversation continuity (`history`, `continue_from`) | ✅ | ✅ | Single prompt per call; supports tool messages in history |

## Provider-Specific Notes

### Gemini

- Context caching uses the Gemini Files API and `cachedContents`.
- Conversation history is translated to `Content` objects with
  `Part.from_function_call` / `Part.from_function_response` for tool turns.
- Gemini does not support `previous_response_id`; conversation state is
  carried entirely via `history`.
- Reasoning: `reasoning_effort` maps to `ThinkingConfig(thinking_level=...)`.
  Full thinking text is returned in `ResultEnvelope.reasoning`. Gemini 2.5
  models use a different control (`thinking_budget`) and will return a
  provider error if `reasoning_effort` is set.

### OpenAI

- File uploads use `purpose="user_data"` with finite `expires_after` metadata.
  Automatic file deletion is not yet managed by Pollux.
- Remote URL support is intentionally narrow: PDFs and images only.
- Conversation can use either explicit `history` or `previous_response_id`
  (via `continue_from`). When `previous_response_id` is set, only tool
  result messages are forwarded from history; the rest is handled
  server-side by OpenAI.
- Reasoning: `reasoning_effort` maps to `reasoning.effort` with automatic
  `summary: "auto"` to request reasoning summaries. Summaries appear in
  `ResultEnvelope.reasoning`; raw reasoning tokens are not exposed by OpenAI.

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
