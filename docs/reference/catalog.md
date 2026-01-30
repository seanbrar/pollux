# Research Catalog

Last reviewed: 2025-09

At‑a‑glance index of research modules, their maturity, and links across Diátaxis.

## Efficiency — Experimental

- Purpose: Compare vectorized batching against a naive per‑prompt baseline over the same workload; produce ratios (tokens, time, calls) and savings.
- Entrypoints: `research.compare_efficiency`, `research.EfficiencyReport`.
- Modes: `auto` (default), `batch`, `aggregate` (prefers JSON for multi‑answer parsing).
- Reproducibility: Reports capture environment hints (version, platform, effective settings).
- Links:
  - How‑to: [Efficiency Workflows](../../how-to/research/efficiency-workflows.md)
  - API: [Research Utilities](../api/research.md)
  - Decision/Concept: [DB‑0001 — Vectorized Batching & Fan‑out (Historical Design Brief)](../../explanation/decisions/DB-0001-vectorization-and-fanout.md)
