# Provider Capabilities

This page defines the current capability contract by provider.

Pollux is **capability-transparent**, not capability-equalizing: providers are allowed to differ, and those differences are surfaced clearly.

## Policy

- Provider feature parity is **not** required for release.
- Unsupported features must fail fast with actionable errors.
- New provider features do not require immediate cross-provider implementation.

## Capability Matrix

| Capability | Gemini | OpenAI | Anthropic | OpenRouter | Notes |
|---|---|---|---|---|---|
| Text generation | ✅ | ✅ | ✅ | ✅ | Core feature |
| Multi-prompt execution (`run_many`) | ✅ | ✅ | ✅ | ✅ | One call per prompt, shared context |
| Local file inputs | ✅ | ✅ | ✅ | ✅ (images/PDFs on supported models) | OpenRouter keeps the local file subset narrow |
| PDF URL inputs | ✅ (via URI part) | ✅ (native `input_file.file_url`) | ✅ (native `document` URL block) | ✅ (supported models) | |
| Image URL inputs | ✅ (via URI part) | ✅ (native `input_image.image_url`) | ✅ (native `image` URL block) | ✅ (supported models) | |
| YouTube URL inputs | ✅ | ⚠️ limited | ⚠️ limited | ❌ | OpenAI/Anthropic parity layers (download/re-upload) are out of scope |
| Explicit context caching (`create_cache`) | ✅ | ❌ | ❌ | ❌ | Persistent cache handles are Gemini-only |
| Implicit prompt caching (`Options.implicit_caching`) | ❌ | ❌ | ✅ | ❌ | Anthropic-only request-level optimization |
| Structured outputs (`response_schema`) | ✅ | ✅ | ✅ | ❌ | OpenRouter support is planned separately |
| Reasoning controls (`reasoning_effort`) | ✅ | ✅ | ✅ | ❌ | Passed through to provider where supported; see notes below |
| Deferred delivery (`delivery_mode="deferred"`) | ❌ | ❌ | ❌ | ❌ | Not supported; raises `ConfigurationError` |
| Tool calling | ✅ | ✅ | ✅ | ❌ | OpenRouter support is planned separately |
| Tool message pass-through in history | ✅ | ✅ | ✅ | ❌ | OpenRouter conversation is text-history only in the current release |
| Conversation continuity (`history`, `continue_from`) | ✅ | ✅ | ✅ | ✅ | Single prompt per call |

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

- Local file uploads use the Anthropic Files API (beta). Supported types:
  images, PDFs, and text files.
- Remote URL support is intentionally narrow: images and PDFs only.
- Implicit prompt caching is enabled with `Options(implicit_caching=True)`.
  Pollux defaults it on for single-call workloads and off for multi-call
  fan-out. Requesting it on unsupported providers raises `ConfigurationError`.
- Reasoning: `reasoning_effort` maps to `output_config.effort`.
  Pollux uses `thinking.type="adaptive"` on adaptive-capable models
  (currently Opus 4.6 and Sonnet 4.6) and falls back to manual thinking budgets on older
  models. The `"max"` effort is strictly limited to Opus 4.6.
- Thinking block replay: when Anthropic returns `thinking` or
  `redacted_thinking` blocks, Pollux preserves them in conversation state and
  replays them verbatim on continuation turns so tool loops remain valid.
- `Options.max_tokens`: limits the output length. Default is `16384` for Anthropic
  (which reserves enough room for all supported manual thinking budgets). Other providers
  currently ignore this option.

### OpenRouter

- OpenRouter is a routed provider: Pollux sends requests to OpenRouter, and the
  selected model slug determines the upstream model family.
- Pollux validates OpenRouter model availability and model-level capabilities
  against the OpenRouter models API metadata.
- The current Pollux OpenRouter support is intentionally narrow:
  text generation, text-history conversation, and verified image/PDF inputs.
- Pollux does not expose OpenRouter routing controls in the public API.
- `continue_from` works through Pollux conversation state replay; there is no
  OpenRouter-specific equivalent to OpenAI's `previous_response_id`.
- OpenRouter multimodal input currently supports:
  local image files, image URLs, local PDFs, and PDF URLs.
- Capability checks are model-driven. For example, image input fails early on
  text-only OpenRouter models.
- Persistent cache handles, structured outputs, reasoning, and tool calling
  are planned as separate OpenRouter follow-ups.

## Error Semantics

When a requested feature is unsupported for the selected provider or release scope, Pollux raises `ConfigurationError` or `APIError` with a concrete hint, instead of degrading silently.

For example, creating a persistent cache with OpenAI:

```python
from pollux import Config, Source, create_cache

config = Config(provider="openai", model="gpt-5-nano")
# This raises immediately:
# ConfigurationError: Provider 'openai' does not support persistent caching
# hint: "Use a provider that supports persistent_cache (e.g. Gemini)."
handle = await create_cache(
    [Source.from_text("hello")], config=config
)
```

The error is raised at `create_cache()` call time because persistent caching
is a provider capability checked before the upload attempt.
