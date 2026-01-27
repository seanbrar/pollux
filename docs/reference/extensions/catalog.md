# Extensions Catalog

At‑a‑glance index of supported extensions, their maturity, and links across Diátaxis.

Last reviewed: 2025‑09

## Conversation — Stable

- Purpose: Immutable, minimal multi‑turn conversation API over the batch pipeline; supports single, sequential, and vectorized execution via `PromptSet`.
- Entrypoints: `Conversation.start()`, `Conversation.ask()`, `Conversation.run(PromptSet)`, `Conversation.with_policy()`, `Conversation.plan()`, `Conversation.analytics()`.
- Advanced: `ConversationEngine` + `ConversationStore` (JSON) for persistence with optimistic concurrency.
- Links:
  - Tutorial: [Conversation — Getting Started](../../tutorials/extensions/conversation-getting-started.md)
  - How‑to (advanced): [Conversation (Advanced)](../../how-to/conversation-advanced.md)
  - API: [Conversation Extension](../api/extensions/conversation.md)
  - Concepts: [Conversation](../../explanation/concepts/conversation.md)
  - ADR: [ADR‑0008 — Conversation](../../explanation/decisions/ADR-0008-conversation.md)

## Token Counting — Stable

- Purpose: Count tokens using the actual Gemini tokenizer with robust domain results and explicit errors.
- Entrypoints: `GeminiTokenCounter`, `ValidContent`, `count_gemini_tokens()`; optional `EstimationHint` for conservative adjustments.
- Notes: No API key required for counting; optional heuristic fallback when SDK unavailable.
- Links:
  - How‑to: [Token Counting](../../how-to/token-counting.md)
  - API: [Token Counting Extension](../api/extensions/token-counting.md)
  - Concepts: [Token Counting & Estimation](../../explanation/concepts/token-counting.md)
  - Calibration (spec): [Token Counting Calibration](../../explanation/deep-dives/token-counting-calibration.md)

## Chunking — Experimental

- Purpose: Utility helpers to split long inputs by approximate token budgets for efficient prompting.
- Entrypoints: `chunk_text_by_tokens()`, `chunk_transcript_by_tokens()`, `TranscriptSegment`, `TranscriptChunk`.
- Notes: Uses planner‑aligned estimation heuristics (no real API required) for approximate token counts.
- Links:
  - How‑to: [Chunking](../../how-to/chunking.md)
  - API: [Chunking Extension](../api/extensions/chunking.md)
  - Related: [Custom Extraction Transforms](../../how-to/custom-transforms.md)

## Provider Adapters (Core seam) — Advanced

- Purpose: Provider adapter interfaces and registry to customize generation/uploads/cache behavior for the Command Pipeline.
- Location: Core pipeline (`pollux.pipeline.adapters.*`), not the `extensions` package, but commonly used by advanced users.
- Links:
  - How‑to: [Provider Adapters](../../how-to/provider-adapters.md)
- Internals API: [Provider Adapters](../internals/provider-adapters.md)
  - Concepts: [Provider Capabilities](../../explanation/concepts/provider-capabilities.md)

## Provider Uploads — Experimental

- Purpose: Pre-upload local files to the provider and wait for an ACTIVE state to avoid race conditions when generating immediately after upload.
- Entrypoints: `preupload_and_wait_active()`, `upload_and_wait_active()`, `UploadResult`, `UploadInactiveError`, `UploadFailedError`.
- Notes: Optional runtime dependency on `google-genai`. Uses resolved config (or `GEMINI_API_KEY`) for credentials. Supports exponential backoff and optional cleanup on timeout.
- Links:
  - How‑to: [Provider Uploads](../../how-to/provider-uploads.md)
  - API: [Provider Uploads](../api/extensions/provider-uploads.md)
  - Related: [Remote File Materialization](../../how-to/remote-file-materialization.md)
