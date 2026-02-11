# Provider Capabilities

This page defines the v1.0 capability contract by provider.

Pollux is **capability-transparent**, not capability-equalizing: providers are allowed to differ, and those differences are surfaced clearly.

## v1.0 Policy

- Provider feature parity is **not** required for release.
- Unsupported features must fail fast with clear errors.
- New provider features do not require immediate cross-provider implementation.

## Capability Matrix (v1.0)

| Capability | Gemini | OpenAI | Notes |
|---|---|---|---|
| Text generation | ✅ | ✅ | Core feature |
| Multi-prompt execution (`run_many`) | ✅ | ✅ | One call per prompt, shared context |
| Local file inputs | ✅ | ✅ | OpenAI uses Files API upload |
| PDF URL inputs | ✅ (via URI part) | ✅ (native `input_file.file_url`) | |
| Image URL inputs | ✅ (via URI part) | ✅ (native `input_image.image_url`) | |
| YouTube URL inputs | ✅ | ⚠️ limited | OpenAI parity layer (download/re-upload) is out of scope for v1.0 |
| Provider-side context caching | ✅ | ❌ | OpenAI provider returns unsupported for caching |
| Structured outputs (`response_schema`) | ✅ | ✅ | JSON-schema path in both providers |
| Reasoning controls (`reasoning_effort`) | ❌ | ❌ | Reserved for future provider enablement |
| Deferred delivery (`delivery_mode="deferred"`) | ❌ | ❌ | Explicitly disabled in v1.0 |
| Conversation continuity (`history`, `continue_from`) | ❌ | ❌ | Reserved/disabled in v1.0 |

## Important OpenAI Notes

- Pollux uploads local files with:
  - `purpose="user_data"`
  - finite `expires_after` metadata
- Automatic file deletion is not part of v1.0 yet.
- Remote URL support in v1.0 is intentionally narrow and explicit:
  - PDFs
  - images

## Error Semantics

When a requested feature is unsupported for the selected provider or release scope, Pollux raises `ConfigurationError` or `APIError` with a concrete hint, instead of degrading silently.

## Design Intent

The goal for v1.0 is a stable and interpretable core. Capability expansion continues in v1.1+ without masking provider realities.
