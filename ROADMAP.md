# Pollux Roadmap

This roadmap is intentionally scope-constrained: ship a stable, high-quality core in v1.0, then expand deliberately.

- **Intent**: communicate priorities and scope boundaries (not a promise or contract).
- **Last updated**: 2026-02-08
- **Status tracking**: Issues and PRs are the source of truth for current work.

## Product Strategy

- **Policy**: Pollux is capability-transparent, not capability-equalizing.
- Provider differences are allowed when clearly documented and surfaced via explicit errors.
- Provider feature parity is a nice-to-have, not a v1.0 requirement.
- New provider features do not require simultaneous implementation across all providers.

## v1.0 (Release Gate)

- Stable core API: `run`, `run_many`, `Config`, `Source`, `Options`, `ResultEnvelope`.
- Correct multimodal behavior for supported provider + input combinations.
- Clear capability boundaries with fail-fast errors for unsupported options.
- Quality gates pass: `make test`, `make lint`, `make typecheck`.

### Explicitly Out of Scope for v1.0

- Feature-parity layers that mask provider differences (example: automatic YouTube download/re-upload for OpenAI).
- Conversation continuity (`history`, `continue_from`).
- Deferred delivery (`delivery_mode="deferred"`).

## Post-1.0 Candidates

- Conversation continuity with clear lifecycle semantics.
- Optional lifecycle controls for provider-managed artifacts (for example, OpenAI uploaded files).
- Expand/maintain the provider capability matrix as features evolve.
- Selective parity adapters only when justified by user demand and maintenance cost.

## References

- Provider-by-provider contract: `docs/reference/provider-capabilities.md`
