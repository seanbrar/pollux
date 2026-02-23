# Provider Capabilities

This page defines the v1.1 capability contract by provider.

Pollux is **capability-transparent**, not capability-equalizing: providers are allowed to differ, and those differences are surfaced clearly.

## v1.1 Policy

- Provider feature parity is **not** required for release.
- Unsupported features must fail fast with clear errors.
- New provider features do not require immediate cross-provider implementation.

## Capability Matrix (v1.1)

| Capability | Gemini | OpenAI | Notes |
|---|---|---|---|
| Text generation | ✅ | ✅ | Core feature |
| Multi-prompt execution (`run_many`) | ✅ | ✅ | One call per prompt, shared context |
| Local file inputs | ✅ | ✅ | OpenAI uses Files API upload |
| PDF URL inputs | ✅ (via URI part) | ✅ (native `input_file.file_url`) | |
| Image URL inputs | ✅ (via URI part) | ✅ (native `input_image.image_url`) | |
| YouTube URL inputs | ✅ | ⚠️ limited | OpenAI parity layer (download/re-upload) is out of scope for v1.1 |
| Provider-side context caching | ✅ | ❌ | OpenAI provider returns unsupported for caching |
| Structured outputs (`response_schema`) | ✅ | ✅ | JSON-schema path in both providers |
| Reasoning controls (`reasoning_effort`) | ❌ | ❌ | Reserved for future provider enablement |
| Deferred delivery (`delivery_mode="deferred"`) | ❌ | ❌ | Explicitly disabled in v1.1 |
| Tool calling | ✅ | ✅ | Tool definitions via `Options.tools`; results in `ResultEnvelope.tool_calls` |
| Tool message pass-through in history | ❌ | ✅ | OpenAI maps tool messages to `function_call`/`function_call_output` items |
| Conversation continuity (`history`, `continue_from`) | ❌ | ✅ | OpenAI-native continuation; single prompt per call; supports tool messages |

## Important OpenAI Notes

- Pollux uploads local files with:
  - `purpose="user_data"`
  - finite `expires_after` metadata
- Automatic file deletion is not part of v1.1 yet.
- Remote URL support in v1.1 is intentionally narrow and explicit:
  - PDFs
  - images

## Error Semantics

When a requested feature is unsupported for the selected provider or release scope, Pollux raises `ConfigurationError` or `APIError` with a concrete hint, instead of degrading silently.

For example, enabling caching with OpenAI:

```python
from pollux import Config

config = Config(
    provider="openai",
    model="gpt-5-nano",
    enable_caching=True,  # not supported for OpenAI in v1.1
)
# At execution time, Pollux raises:
# ConfigurationError: Provider does not support caching
# hint: "Disable caching or choose a provider with caching support."
```

The error is raised at execution time (not at `Config` creation) because
caching support is a provider capability checked during plan execution.
