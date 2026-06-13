# Pollux Roadmap

This roadmap is intentionally scope-constrained. Pollux is already past the
"ship the core at all costs" phase; the next phase is to make the core more
trustworthy, more legible, and harder to misuse.

- **Intent**: communicate priorities and scope boundaries, not promises.
- **Last updated**: 2026-04-22
- **Current status**: v1.8 ships reasoning budget tokens, normalized
  `cached_tokens` usage reporting across providers, a text-only `local`
  provider for self-hosted OpenAI-compatible servers, and removes the deprecated
  `Options.delivery_mode` shim.
- **Status tracking**: Issues and PRs are the source of truth for active work.

## Product Strategy

- **Policy**: Pollux is capability-transparent, not capability-equalizing.
- Pollux owns orchestration primitives, not full application workflows.
- Prefer stronger guarantees, clearer docs, and sharper errors over a broader
  public API.
- New surface area should earn its place by removing repeated downstream
  boilerplate without hiding meaningful provider differences.
- Upstream concerns stay upstream: model quality, pricing, provider-side
  latency, and feature availability belong to providers.
- Downstream concerns stay downstream: scheduling, job queues, human review,
  storage, business workflows, and long-running agent policy belong to
  applications using Pollux.

## Current Position

The core library now covers the main orchestration responsibilities it set out
to own:

- Stable entry points for realtime and deferred execution:
  `run()`, `run_many()`, `defer()`, `defer_many()`,
  `inspect_deferred()`, `collect_deferred()`, `cancel_deferred()`.
- Multimodal source handling across the supported cloud provider matrix, plus
  a text-only `local` provider for self-hosted OpenAI-compatible servers.
- Source patterns: fan-out, fan-in, and broadcast.
- Context reuse through explicit caching, implicit caching where exposed, and
  provider-managed prompt caching where available.
- Structured outputs, tool calling, conversation continuity, and reasoning
  controls (`reasoning_effort`, `reasoning_budget_tokens`) where providers
  support them.
- Usage surface normalized across providers, including `reasoning_tokens` and
  `cached_tokens` in the result envelope when providers report them.

## Scope Philosophy

Pollux is demand-driven. New features ship when a concrete use case makes
them necessary, not to pre-empt hypothetical needs or to match capability
matrices from larger frameworks. Issues and PRs are welcome; the bar for
expansion is whether a change makes an existing contract stronger or removes
real downstream boilerplate, not whether it broadens surface area.

This keeps the roadmap intentionally short. "More features by default" is not
the goal; the goal is a small core that stays trustworthy under real use.

## Current Candidates

Concrete items currently on the shortlist. None are commitments, and the list
is expected to stay short. Discovered follow-ups are tracked in GitHub issues.

- **Gemini flex inference tier** — evaluate provider-specific support for
  Google's flex inference pricing tier (lower cost, higher latency).

## High-Bar / Not Planned

The following are intentionally outside Pollux's target shape unless a very
strong case emerges:

- Workflow schedulers, background workers, cron abstractions, or queue systems
- Vector stores, retrieval frameworks, or document indexing pipelines
- Agent runtimes, planning frameworks, or memory systems
- Automatic parity layers that hide fundamental provider limitations
- Provider-agnostic knobs for every provider-specific feature
- Cross-job recovery systems that own application-level orchestration

## References

- Provider contract: `docs/reference/provider-capabilities.md`
- Testing philosophy: `TESTING.md`
- Contributor guidance: `docs/contributing.md`
