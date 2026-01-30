# DB-0001 — Vectorized Batching & Fan-out (Historical Design Brief)

Status: Informational (Historical)
Date: 2025-08-22
Scope: Core pipeline (planner, API handler, result builder, rate limiting)

Preface: This focused design brief was written to communicate a specific architectural concern — preserving per‑prompt identity in vectorized requests and orchestrating large fan‑out safely. It was not a solicitation for external proposals. The thinking here informed ADR‑0010, where the neutral `ExecutionOptions` seam superseded ad‑hoc hints for planner/result/cache intent.

## 1) Current State (Summary)

- Prompts: Minimal planner joins multiple prompts into a single text payload. ResultBuilder pads/truncates to the requested count, but only one meaningful answer is typically produced in the mock path.
- Sources: Multiple sources per call are supported; files become placeholders and may be uploaded by API handler.
- Rate limits: Per-call rate handling only (RateLimitHandler); no global orchestration for many concurrent calls.
- Telemetry: Metrics include durations, token validation, and optional usage; no structured per-prompt metrics in batch mode.

## 2) Requirements to Cover

- R1: True multi-prompt vectorization: one API call, N prompts → N distinct answers with stable alignment/order.
- R2: Multi-source, multi-prompt batching: accept multiple sources and multiple prompts in one call; answers should consider all sources collectively.
- R3: Large fan-out: run M independent commands concurrently (e.g., same question against 100 papers) and collect M answers, observing tier rate limits.
- R4: Per-prompt telemetry: usage/tokens/latency per prompt when vectorized.
- R5: Deterministic cache reuse: optional extension-provided hints (cache key/artifacts) integrated into planning without coupling core to any extension.

## 3) High-level Gaps

- G1: Planner collapses multiple prompts → loses per-prompt identity.
- G2: API handler/adapter interface lacks an explicit batch call contract beyond a flat parts list.
- G3: ResultBuilder has no shape for per-prompt extraction when the provider returns batch outputs.
- G4: No core “batch runner” to schedule many commands with bounded concurrency and rate-aware pacing.
- G5: No neutral seam to accept extension hints (cache identity) in planning.

## 4) High-level Proposals

- P1: Preserve prompt vector
  - Keep `InitialCommand.prompts` as a tuple and thread that through to planner and API handler. Planner builds `APICall` that encodes multiple prompts distinctly (e.g., multiple `TextPart`s or an `api_prompts` field at call level).
- P2: Adapter batch contract
  - Introduce an optional adapter capability for batch generate: `generate_batch(model_name, prompts, api_config, parts)` returning a structured response aligned with prompts.
  - Fallback: if not supported, planner still joins prompts (current behavior), but ResultBuilder notes it, and vectorized callers can choose sequential fallback.
- P3: ResultBuilder per-prompt extraction
  - Add a branch to detect batch responses and build `answers: list[str]` aligned to prompts with optional `per_prompt_metrics` included in `metrics` under a reserved key.
- P4: Batch runner (or BatchExecutor)
  - Provide a small orchestrator to execute many `InitialCommand`s concurrently with bounded concurrency and integrated RateLimitHandler checks (global pacing). Return a stable `list[ResultEnvelope]` in input order.
- P5: Planning options (neutral seam)
  - Accept a neutral, typed options bag (now `ExecutionOptions`) including a deterministic cache key and known artifacts. The planner/cache/result stages read these options without provider coupling.

## 5) API Sketches (High-level)

- Adapter capability:
  - `class GenerationAdapter: async def generate_batch(self, model_name: str, prompts: tuple[str, ...], api_parts: tuple[APIPart, ...], api_config: dict[str, object]) -> Any: ...`
  - API handler: detect and use batch path when capability present; otherwise fallback to sequential internally or preserve existing behavior.
- Result envelope additions:
  - `metrics["per_prompt"]: list[dict]` (optional) for per-prompt telemetry; absent if unsupported.
- Batch runner:
  - `async def run_batch(executor: GeminiExecutor, commands: list[InitialCommand], concurrency: int = 8) -> list[dict[str, Any]]`

## 6) Risks & Trade-offs

- Provider heterogeneity: not all adapters provide batch answers or per-prompt metrics; the design must tolerate missing structures.
- Complexity creep: batch runner must remain small and composable; keep orchestration optional and library-owned.
- Backwards compatibility: preserve existing single-prompt flow; vectorization is opt-in where supported.

## 7) Milestones

- M1: Preserve prompt vectors end-to-end; ResultBuilder recognizes batch answers; vectorized mode stable in mock path.
- M2: Adapter batch capability for the real provider path; API handler integration.
- M3: Per-prompt telemetry surfaced when provider supports it; metrics normalization.
- M4: Batch runner with bounded concurrency and tier-aware pacing.
- M5: Optional planning hints; wire to deterministic cache key without coupling to extensions.

## 8) Evaluation Plan

- Scripts: use examples/test_data/research_papers and test_files to run small batches with one-sentence prompts; confirm answer alignment and batch metrics.
- Regression: continue to pad/truncate answers to expected counts and record schema/contract violations.

## See also

- ADR‑0010 — Hint Capsules → ExecutionOptions (adopted seam that emerged from this brief)
