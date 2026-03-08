<!-- Intent: Define the user-facing capability contract by provider. Clarify
     where provider behavior differs, especially for OpenRouter's routed
     multimodal support. Do NOT explain internal request shaping or SDK
     implementation details. Assumes the reader already knows Pollux's core
     API surface. Register: reference. -->

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
| Local file inputs | ✅ | ✅ | ✅ | ✅ (images and PDFs) | OpenRouter keeps the local file subset narrow |
| PDF URL inputs | ✅ (via URI part) | ✅ (native `input_file.file_url`) | ✅ (native `document` URL block) | ⚠️ best-effort | Prefer local PDFs when reliability matters |
| Image URL inputs | ✅ (via URI part) | ✅ (native `input_image.image_url`) | ✅ (native `image` URL block) | ⚠️ best-effort on supported models | Remote fetch behavior can vary by route |
| YouTube URL inputs | ✅ | ⚠️ limited | ⚠️ limited | ❌ | OpenAI/Anthropic parity layers (download/re-upload) are out of scope |
| Explicit context caching (`create_cache`) | ✅ | ❌ | ❌ | ❌ | Persistent cache handles are Gemini-only |
| Implicit prompt caching (`Options.implicit_caching`) | ❌ | ❌ | ✅ | ❌ | Anthropic-only request-level optimization |
| Structured outputs (`response_schema`) | ✅ | ✅ | ✅ | ⚠️ model-dependent | Requires an OpenRouter model that advertises `response_format` or `structured_outputs` |
| Reasoning controls (`reasoning_effort`) | ✅ | ✅ | ✅ | ⚠️ model-dependent | Passed through to provider where supported; see notes below |
| Deferred delivery (`delivery_mode="deferred"`) | ❌ | ❌ | ❌ | ❌ | Not supported; raises `ConfigurationError` |
| Tool calling | ✅ | ✅ | ✅ | ⚠️ model-dependent | Requires an OpenRouter model that advertises `tools`; forced tool use may also require `tool_choice` |
| Tool message pass-through in history | ✅ | ✅ | ✅ | ⚠️ model-dependent | Works on OpenRouter models that support tool calling |
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
- Reasoning: Gemini 3 models (for example `gemini-3-flash-preview`) return
  full thinking text in `ResultEnvelope.reasoning`. Gemini 2.x models do not
  support `reasoning_effort` and return a provider error if it is set.

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
- Reasoning: OpenAI provides reasoning summaries (not raw traces) in
  `ResultEnvelope.reasoning`. Token counts appear in
  `ResultEnvelope.usage["reasoning_tokens"]` when the model returns them.
  Some older models reject `reasoning_effort`.

### Anthropic

- Local file uploads use the Anthropic Files API (beta). Supported types:
  images, PDFs, and text files.
- Remote URL support is intentionally narrow: images and PDFs only.
- Implicit prompt caching is enabled with `Options(implicit_caching=True)`.
  Pollux defaults it on for single-call workloads and off for multi-call
  fan-out. Requesting it on unsupported providers raises `ConfigurationError`.
- Reasoning: thinking text appears in `ResultEnvelope.reasoning`. All
  `claude-4.x` models support `reasoning_effort`; the `"max"` level is
  Opus 4.6 only.
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
- The current Pollux OpenRouter support includes text generation, conversation
  continuity, model-gated structured outputs, model-gated tool calling, and
  verified image/PDF inputs.
- Pollux does not expose OpenRouter routing controls in the public API.
- `continue_from` works through Pollux conversation state replay; there is no
  OpenRouter-specific equivalent to OpenAI's `previous_response_id`.
- `continue_tool()` works through the same replay path. Pollux carries prior
  assistant tool calls and tool-result messages forward through history when
  the selected OpenRouter model supports tool calling.
- Structured outputs and tool calling are model-dependent on OpenRouter.
  Pollux checks the OpenRouter models API metadata before dispatch and raises
  `ConfigurationError` when a selected model does not advertise the required
  parameters.
- OpenRouter multimodal input currently supports:
  local image files, image URLs, local PDFs, and PDF URLs.
- Image input is model-driven. If the selected OpenRouter model does not accept
  images, Pollux fails early with `ConfigurationError`.
- Image routes can still fail at execution time even when the model metadata
  advertises image input. OpenRouter may choose an upstream route that rejects
  the image payload or cannot fetch the remote URL.
- PDF input uses OpenRouter's provider-side PDF parser rather than the model's
  native `input_modalities` metadata. Pollux therefore allows PDFs even when a
  model does not advertise native `file` input.
- Local PDFs are the most reliable OpenRouter document path in the current
  release.
- PDF URLs are best-effort. Some routes parse them correctly, some return
  `PDF_UNAVAILABLE`, and some reject the request before the model sees the
  document.
- When an OpenRouter route rejects or mishandles an image or PDF, Pollux
  surfaces that upstream provider error. The first fix is usually choosing a
  different OpenRouter model or route. For documents, another good fallback is
  downloading the PDF locally and sending it with `Source.from_file()`.
- Unsupported OpenRouter file types fail fast. For example, local CSV uploads
  raise `ConfigurationError`.
- Persistent cache handles remain unsupported on OpenRouter in the current release.
- Reasoning: works on OpenRouter models that support reasoning. Thinking text
  appears in `ResultEnvelope.reasoning`, and token counts in
  `ResultEnvelope.usage["reasoning_tokens"]` when available.

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
