# Extensions Overview

Purpose: Orient users to optional, add‑on modules that build on the core Command Pipeline. Extensions are designed to depend only on core public types and the single executor seam, without expanding the public surface area of core.

What this page provides:

- Scope and maturity guidance for each extension (Stable/Experimental).
- Quick pointers across Diátaxis: tutorials, how‑to guides, API reference, concepts/specs, and ADRs.
- Safety notes and prerequisites so you can pick the right tool quickly.

Who is this for:

- Users who finished the Quickstart and want higher‑level workflows (conversation), utilities (chunking), or measurement (token counting).
- Teams evaluating which optional pieces are stable enough for production.

Prerequisites and safety:

- Python 3.13 installed; project set up via `make install-dev`.
- Real API calls may be involved depending on the extension. Set `POLLUX_TIER` to match your billing to avoid throttling. See How‑to → [Verify Real API](../how-to/verify-real-api.md).
- Token counting uses Google’s free token counting endpoint and does not require an API key for counting; rate limits may apply.

Last reviewed: 2025‑09

## At a Glance

- Conversation (Stable)
  - What: Minimal, immutable multi‑turn conversation facade over the batch pipeline.
  - Key API: `Conversation.start()`, `Conversation.ask()`, `Conversation.run(PromptSet)`, `Conversation.with_policy()`, `Conversation.plan()`, `Conversation.analytics()`; execution modes via `PromptSet.single|sequential|vectorized`.
  - Advanced: Optional `ConversationEngine` + `ConversationStore` for persistence with optimistic concurrency.
- Links:
  - Tutorial: [Conversation — Getting Started](../tutorials/extensions/conversation-getting-started.md)
  - How‑to (advanced): [Conversation (Advanced)](../how-to/conversation-advanced.md)
  - API: [Conversation Extension](../reference/api/extensions/conversation.md)
  - Concepts: [Conversation](../explanation/concepts/conversation.md)
  - ADR: [ADR‑0008 — Conversation](../explanation/decisions/ADR-0008-conversation.md)

- Token Counting (Stable)
  - What: Count tokens using the actual Gemini tokenizer; robust domain results (`TokenCountSuccess`/`TokenCountFailure`).
  - Key API: `GeminiTokenCounter`, `ValidContent`, `count_gemini_tokens()`; optional `EstimationHint` for conservative adjustments.
  - Notes: No API key required for token counting; optional fallback estimation available when SDK unavailable.
- Links:
  - How‑to: [Token Counting](../how-to/token-counting.md)
  - API: [Token Counting Extension](../reference/api/extensions/token-counting.md)
  - Concepts: [Token Counting & Estimation](../explanation/concepts/token-counting.md)
  - Calibration (spec): [Token Counting Calibration](../explanation/deep-dives/token-counting-calibration.md)

- Chunking (Experimental)
  - What: Utility helpers to split long inputs by approximate token budgets.
  - Key API: `chunk_text_by_tokens()`, `chunk_transcript_by_tokens()`, `TranscriptSegment`, `TranscriptChunk`.
  - Notes: Uses the same estimation heuristics as the planner’s Gemini adapter for approximation.
  - Links: [Chunking](../how-to/chunking.md), [API](../reference/api/extensions/chunking.md); see also [Custom Extraction Transforms](../how-to/custom-transforms.md) for adjacent patterns.

- Provider Uploads (Experimental)
  - What: Pre-upload local files to the provider and wait for an ACTIVE state to reduce race conditions when generating immediately after upload.
  - Key API: `preupload_and_wait_active()`, `upload_and_wait_active()`, `UploadResult`, `UploadInactiveError`, `UploadFailedError`.
  - Notes: Optional runtime dependency on `google-genai`. Uses resolved config or `GEMINI_API_KEY` for credentials; supports exponential backoff and optional cleanup on timeout.
  - Links: [How‑to](../how-to/provider-uploads.md), [API](../reference/api/extensions/provider-uploads.md); related: [Remote File Materialization](../how-to/remote-file-materialization.md)

- Provider Adapters (Advanced, Core seam)
  - What: Adapter interfaces and registry that customize provider behavior for the Command Pipeline.
  - Notes: These live under the core pipeline (not the `extensions` package) but are often used by advanced users integrating providers.
- Links: [Provider Adapters](../how-to/provider-adapters.md), [Internals API](../reference/internals/provider-adapters.md), [Provider Capabilities](../explanation/concepts/provider-capabilities.md)

## Guidance and Support Policy

- Stability labels
  - Stable: Supported for general use; changes follow semantic versioning where possible and ship with migration notes.
  - Experimental: APIs may change based on feedback; expect minor breaking changes between versions.
- Design constraints
  - Extensions consume only public core types and the single executor seam.
  - No implicit side effects: pure compile‑then‑execute; persistence is opt‑in and separated via stores/engines when provided.
  - One fact, one place: Factual API details live in reference pages (often generated via mkdocstrings).

## See Also

- Reference → [Extensions Catalog](../reference/extensions/catalog.md)
- Tutorials → [Extensions](../tutorials/extensions/index.md)
- How‑to → Extensions:
  - Conversation (Advanced): [conversation-advanced.md](../how-to/conversation-advanced.md)
  - Token Counting: [token-counting.md](../how-to/token-counting.md)
  - Provider Adapters: [provider-adapters.md](../how-to/provider-adapters.md)
  - Chunking: [chunking.md](../how-to/chunking.md)
  - Provider Uploads: see [Remote File Materialization](../how-to/remote-file-materialization.md)
- Concepts → Extensions:
  - Conversation: [conversation.md](../explanation/concepts/conversation.md)
  - Token Counting & Estimation: [token-counting.md](../explanation/concepts/token-counting.md)
