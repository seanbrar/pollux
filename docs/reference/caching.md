# Caching — Reference

Last reviewed: 2025-09

Purpose: Document the current, factual knobs and types related to context caching. This page reflects the shipped API; see ADR‑0011 for the design direction and planner simplifications.

See also:

- Decisions → [ADR‑0011 Cache Policy & Planner Simplification](../explanation/decisions/ADR-0011-cache-policy-and-planner-simplification.md)
- Concepts → [Result Building](../explanation/concepts/result-building.md)
- API → [Config](api/config.md)

## Configuration Fields

Global enablement and default TTL are part of the resolved config.

- `enable_caching: bool` — master switch for enabling caching behavior when supported by provider/model.
- `ttl_seconds: int` — default cache TTL in seconds (non‑negative). Applies when a cache entry is created.

Find these fields under `pollux.config` and the effective values via `pollux-config show` or `pollux-config audit`.

## Execution Options (per‑call)

For granular, per‑call control, use `ExecutionOptions`. See detailed API docs on the Core Types page:

- Cache options: [pollux.core.execution_options.CacheOptions](api/core.md#pollux.core.execution_options.CacheOptions)
- Cache policy: [pollux.core.execution_options.CachePolicyHint](api/core.md#pollux.core.execution_options.CachePolicyHint)
- Execution options: [pollux.core.execution_options.ExecutionOptions](api/core.md#pollux.core.execution_options.ExecutionOptions)

Notes:

- `CacheOptions` controls deterministic identity, reuse‑only behavior, and optional TTL override for a single execution.
- `CachePolicyHint` provides planner‑scoped policy hints (e.g., only create on the first turn) without provider coupling.
- `ExecutionOptions.cache_override_name` can attach a best‑effort cache name at execution time (e.g., when overriding plan annotations).

## Internals & Stages

Caching is applied within the pipeline by the Cache Stage and consumed by the API Handler when the provider supports it. Registry interactions are in‑memory and process‑local.

- Internals → [Pipeline](internals/pipeline.md)
- Internals → [Results](internals/results.md)
- Internals → [Adapters](internals/adapters.md)

## Safety

- TTL must be `>= 0`. Negative TTLs are rejected by validation.
- Large payloads: creation may stream significant bytes; consult environment limits and the provider’s constraints.
