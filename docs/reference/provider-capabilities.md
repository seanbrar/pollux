<!-- Intent: Define the user-facing capability contract by provider. Clarify
     where provider behavior differs, especially for OpenRouter's routed
     multimodal support. Do NOT explain internal request shaping or SDK
     implementation details. Assumes the reader already knows Pollux's core
     API surface. Register: reference. -->

# Provider Capabilities

This page defines the current capability contract by provider.

Pollux is **capability-transparent**, not capability-equalizing: providers are allowed to differ, and those differences are surfaced explicitly.

## Policy

- Provider feature parity is **not** required for release.
- Unsupported features must fail fast with actionable errors.
- New provider features do not require immediate cross-provider implementation.

## Capability Matrix

Use this table as a release contract, not a model catalog. A ✅ means Pollux
implements the feature for the provider. A ⚠️ means the feature depends on the
selected model, route, or backing server. A ❌ means Pollux rejects the request
before dispatch or the provider page below calls out why it is out of scope.

### Core Execution

| Capability | Gemini | OpenAI | Anthropic | OpenRouter | Local | Notes |
|---|---|---|---|---|---|---|
| Text generation | ✅ | ✅ | ✅ | ✅ | ✅ | Core feature |
| Multi-prompt execution (`run_many`) | ✅ | ✅ | ✅ | ✅ | ✅ | One call per prompt, shared context |
| Structured outputs (`output` schema) | ✅ | ✅ | ✅ | ⚠️ model-dependent | ✅ (JSON schema mode) | Local sends `json_schema`; schema enforcement quality varies by server |
| Deferred delivery (`defer`, `inspect_deferred`, `collect_deferred`, `cancel_deferred`) | ✅ | ✅ | ✅ | ❌ | ❌ | Use the deferred API directly |

### Inputs

| Capability | Gemini | OpenAI | Anthropic | OpenRouter | Local | Notes |
|---|---|---|---|---|---|---|
| Local file inputs | ✅ | ✅ | ✅ | ✅ (images and PDFs) | ❌ | OpenRouter keeps the local file subset narrow; local provider is text-only |
| PDF URL inputs | ✅ (via URI part) | ✅ (native `input_file.file_url`) | ✅ (native `document` URL block) | ⚠️ best-effort | ❌ | Prefer local PDFs when reliability matters |
| Image URL inputs | ✅ (via URI part) | ✅ (native `input_image.image_url`) | ✅ (native `image` URL block) | ⚠️ best-effort on supported models | ❌ | Remote fetch behavior can vary by route |
| Text/document URL inputs | ✅ (Gemini URL Context opt-in) | ✅ (native `input_file.file_url`) | ❌ | ⚠️ best-effort | ❌ | Provider-specific MIME support varies |
| YouTube URL inputs | ✅ | ⚠️ limited | ⚠️ limited | ❌ | ❌ | OpenAI/Anthropic parity layers (download/re-upload) are out of scope |

### Caching

| Capability | Gemini | OpenAI | Anthropic | OpenRouter | Local | Notes |
|---|---|---|---|---|---|---|
| Persistent caching (`CachePolicy`) | ✅ | ❌ | ❌ | ❌ | ❌ | Persistent caches are Gemini-only |
| Provider-managed caching (`cache`) | ❌ | ❌ | ✅ | ❌ | ❌ | Anthropic-only; see [caching docs](../caching.md#provider-managed-caching-anthropic) |
| Automatic prompt caching (provider-side) | ✅ | ✅ | ❌ | ⚠️ route-dependent | ⚠️ server-dependent | Provider behavior, not a Pollux API; see [caching docs](../caching.md#three-caching-paths) |

### Reasoning And Agents

| Capability | Gemini | OpenAI | Anthropic | OpenRouter | Local | Notes |
|---|---|---|---|---|---|---|
| Reasoning output (`result.reasoning`) | ✅ | ✅ | ✅ | ⚠️ model-dependent | ⚠️ server/model-dependent | Pollux surfaces reasoning text when providers return it |
| `reasoning_effort` | ✅ | ✅ | ✅ | ⚠️ model-dependent | ❌ | Qualitative level (`"low"`, `"medium"`, `"high"`, etc.); exact model support remains provider-defined |
| `reasoning_budget_tokens` | ✅ | ❌ | ✅ | ❌ | ❌ | Explicit token ceiling; mutually exclusive with `reasoning_effort` |
| Function tool calling | ✅ | ✅ | ✅ | ⚠️ model-dependent | ✅ (server-dependent) | Pollux-normalized client/application tools; local trusts the server, no capability probe |
| Provider-hosted tools | ⚠️ via `provider_options` | ⚠️ via `provider_options` | ⚠️ via `provider_options` | ⚠️ via `provider_options` | ⚠️ server-dependent | Raw provider escape hatch; not normalized by Pollux |
| Tool message pass-through in history | ✅ | ✅ | ✅ | ⚠️ model-dependent | ✅ (server-dependent) | Local replays assistant tool calls and `tool`-role results verbatim |
| Streaming (`stream()` → `Event`) | ✅ | ✅ | ✅ | ✅ | ✅ | Streamed `done.output` matches the non-streaming `Output` |
| Conversation continuity (`history`, `continuation`) | ✅ | ✅ | ✅ | ✅ | ✅ | Single prompt per call |

For when deferred delivery is a fit and how to structure code around provider
jobs, see [Building With Deferred Delivery](../building-with-deferred-delivery.md).

## Provider-Specific Notes

### Gemini

- Persistent caching uses the Gemini Files API.
- Deferred delivery uses the Gemini Batch API through Pollux's deferred entry
  points.
- Video sources can carry Gemini-specific clipping and FPS controls via
  `Source.with_gemini_video_settings(...)`.
- HTTP(S) URI sources can opt into Gemini URL Context via
  `Source.from_uri(...).with_gemini_url_context()`. This performs request-time
  retrieval, surfaces URL retrieval metadata in diagnostics, and cannot be used
  with persistent caching.
- Those controls are intentionally not normalized across providers. Pollux
  keeps them explicit so portability decisions stay in caller code.
- Gemini also caches repeated long prefixes automatically. Pollux does not
  expose a toggle for that path.
- Gemini does not support `previous_response_id`; conversation state is
  carried entirely via `history`.
- Tool parameter schemas are normalized at the provider boundary:
  `additionalProperties` is stripped because the Gemini API rejects it.
- Reasoning: Gemini returns full thinking text in `output.reasoning`
  when the selected model and reasoning mode support it. Pollux forwards both
  `reasoning_effort` and `reasoning_budget_tokens`; model-specific acceptance
  is enforced by the Gemini API.

### OpenAI

- File uploads are configured to automatically expire on the OpenAI side.
  Pollux also performs best-effort cleanup of uploaded files after execution.
- Deferred delivery uses the OpenAI Batch API through Pollux's deferred entry
  points.
- OpenAI caches repeated long prefixes automatically. OpenAI-specific cache
  routing controls can be passed through `provider_options`.
- Remote URL support includes images plus PDFs, text-like files, and common
  document/spreadsheet/presentation formats accepted by OpenAI `input_file`
  URLs. Audio, video, and unknown binary URLs remain unsupported.
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
  `output.reasoning`. Token counts appear in
  `output.usage.reasoning_tokens` when the model returns them.
  Some older models reject `reasoning_effort`. OpenAI does not accept
  `reasoning_budget_tokens`; Pollux raises `ConfigurationError` before the
  request is dispatched.

### Anthropic

- Local file uploads use the Anthropic Files API (beta). Supported types:
  images, PDFs, and plaintext files. Convert CSV, Markdown, Office files, and
  other text-like formats to `text/plain` before sending.
- Deferred delivery uses the Anthropic Message Batches API through Pollux's
  deferred entry points.
- Remote URL support is intentionally narrow: images and PDFs only.
- Provider-managed (automatic prompt) caching is on by default for single-call
  workloads and off for multi-call fan-out. Set `cache="none"` on the
  `Environment` to opt out.
- See [current caching scope](../caching.md#current-pollux-scope) for what
  Pollux exposes from Anthropic's caching surface.
- Reasoning: thinking text appears in `output.reasoning`.
  `reasoning_effort` and `reasoning_budget_tokens` are both forwarded for
  Anthropic models that support them. Exact model support and budget floors
  are enforced by Anthropic. Pollux routes current Opus adaptive-thinking
  models through Anthropic's adaptive thinking mode.
- Thinking block replay: when Anthropic returns `thinking` or
  `redacted_thinking` blocks, Pollux preserves them in conversation state and
  replays them verbatim on continuation turns so tool loops remain valid. This
  holds for `stream()` too: signed thinking blocks are reassembled from the
  stream, so a streamed extended-thinking + tool turn continues identically to
  the non-streaming path.
- `max_tokens`: limits the output length. Default is `16384` for Anthropic,
  which leaves room for thinking output at all effort levels. Other providers
  currently ignore this option.

### OpenRouter

- OpenRouter is a routed provider: Pollux sends requests to OpenRouter, and the
  selected model slug determines the upstream model family.
- Pollux validates OpenRouter model availability and capabilities.
- The current Pollux OpenRouter support includes text generation, conversation
  continuity, model-gated structured outputs, model-gated tool calling, and
  verified image/PDF inputs.
- Pollux does not expose OpenRouter routing controls in the public API.
- `continuation` works through Pollux conversation state replay; there is no
  OpenRouter-specific equivalent to OpenAI's `previous_response_id`.
- `interact()` and `stream()` work through the same replay path. Pollux carries prior
  assistant tool calls and tool-result messages forward through history when
  the selected OpenRouter model supports tool calling.
- Structured outputs and tool calling are model-dependent on OpenRouter.
  Pollux raises `ConfigurationError` when a selected model does not support
  the required capabilities.
- OpenRouter multimodal input currently supports:
  local image files, image URLs, local PDFs, and PDF URLs.
- Image input is model-driven. If the selected OpenRouter model does not accept
  images, Pollux fails early with `ConfigurationError`.
- Image routes can still fail at execution time even when the model supports
  image input. OpenRouter may choose an upstream route that rejects the image
  payload or cannot fetch the remote URL.
- PDF input uses OpenRouter's provider-side PDF parser. Pollux allows PDFs
  even when a model does not natively support file input.
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
- Persistent caching remains unsupported on OpenRouter in the current release.
- OpenRouter supports automatic prompt caching on many routed providers.
  Pollux does not expose OpenRouter-specific cache controls.
- Reasoning: works on OpenRouter models that support reasoning. Thinking text
  appears in `output.reasoning`, and token counts in
  `output.usage.reasoning_tokens` when available. OpenRouter does
  not accept `reasoning_budget_tokens`; Pollux raises `ConfigurationError`
  before dispatch. Under `stream()`, reasoning text is surfaced for display but
  the `reasoning_details` replay state is not reconstructed from the stream
  (best-effort context, not a continuation requirement).

### Local

- The local provider targets self-hosted servers that speak the OpenAI Chat
  Completions wire format. It is Pollux's orchestration layer pointed at a
  local inference engine, not a general compatibility shim for every
  OpenAI-compatible API.
- `base_url` is required (via `Config(base_url=...)` or the
  `POLLUX_LOCAL_BASE_URL` environment variable). `api_key` is optional; most
  self-hosted servers ignore it.
- The supported surface is text or tool calls in, text or JSON out. Pollux
  passively surfaces model-native reasoning text when the server returns
  `reasoning_content`, but it does not send portable reasoning controls.
  File uploads, remote URLs, multimodal parts, reasoning controls, persistent
  and provider-managed caching, and deferred delivery are not supported.
  Requesting any of them raises `ConfigurationError` before dispatch.
- Function tool calling is supported through the standard `tools` /
  `tool_choice` fields: Pollux sends the declarations, replays assistant tool
  calls and tool results on continuation turns, and surfaces returned tool calls
  on the response. Like JSON mode, this trusts the server: there is no
  per-model capability probe, and a server that ignores `tools` never emits
  tool calls.
- Structured outputs use OpenAI-compatible JSON schema mode
  (`response_format={"type": "json_schema", ...}`). Server-side schema
  enforcement quality varies. Pydantic schema inputs are validated downstream
  when building `output.structured`; raw JSON Schema dicts rely on the
  local server's schema enforcement. When a server returns non-JSON text, or a
  Pydantic response fails model validation, the corresponding entry in
  `output.structured` is `None`.
- Automatic prompt caching depends entirely on the backing inference engine.
  Pollux does not expose a toggle for it.
- Conversation continuity uses `history`; there is no server-side session ID
  equivalent to OpenAI's `previous_response_id`.
- For swap patterns between local and cloud providers, see
  [Writing Portable Code Across Providers](../portable-code.md#running-against-a-self-hosted-model).

## Error Semantics

When a requested feature is unsupported for the selected provider or release
scope, Pollux raises `ConfigurationError` or `APIError` with a concrete hint,
instead of degrading silently.

For example, creating a persistent cache with OpenAI:

```python
from pollux import CachePolicy, Config, Source, prepare_environment

config = Config(provider="openai", model="gpt-5-nano")
# This raises immediately:
# ConfigurationError: Provider 'openai' does not support persistent caching
# hint: "Use a provider that supports persistent_cache (e.g. Gemini)."
environment = await prepare_environment(
    sources=[Source.from_text("hello")],
    cache=CachePolicy(),
    config=config,
)
```

The error is raised at `prepare_environment()` call time because persistent
caching is a provider capability checked before the upload attempt.

For the deferred lifecycle contract and out-of-scope options, see
[Submitting Work for Later Collection](../submitting-work-for-later-collection.md).
