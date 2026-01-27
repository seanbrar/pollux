# Research Overview

Purpose: Orient advanced users and researchers to modules and workflows intended for evaluation, prototyping, or measurement (e.g., efficiency, accuracy). Research modules are separate from core and extensions and may evolve independently.

Who this is for:

- Advanced users evaluating vectorization impacts, token economics, and pipeline timing.
- Researchers prototyping workflows and comparing shapes (aggregate vs batch) with reproducible metrics.

Prerequisites and safety:

- Python 3.13; project installed (`make install-dev` or `pip install -e .[dev]`).
- Real API calls may be involved. Set `GEMINI_API_KEY` and match `POLLUX_TIER` to your billing to avoid throttling.
- Experiments can incur costs and rate limits. Start small (`trials=1`, modest corpora). `ensure_uncached=True` increases request volume; use judiciously.

Status: pre‑1.0 (APIs may change until first stable release).

Last reviewed: 2025‑09

## At a Glance

- Efficiency (Experimental)
  - What: Compare vectorized batching against a naive per‑prompt baseline over the same workload; produce ratios (tokens, time, calls) and savings.
  - Key API: `research.compare_efficiency`, `research.EfficiencyReport`.
  - Modes: `auto` (default), `batch`, `aggregate` (prefers JSON for multi‑answer parsing).
  - Links:
    - How‑to: [Efficiency Workflows](../how-to/research/efficiency-workflows.md)
    - API: [Research Utilities](../reference/api/research.md)
    - Concept/decision: [DB‑0001 — Vectorized Batching & Fan‑out (Historical Design Brief)](../explanation/decisions/DB-0001-vectorization-and-fanout.md)

## Guidance and Support Policy

- Stability: Research modules are experimental; expect iteration based on findings and feedback.
- Design constraints: Lives off the core surface to avoid expanding top‑level APIs; one fact, one place—API details live in the reference.
- Reproducibility: Reports capture environment hints (version, platform, effective settings) to aid comparisons.

## See Also

- Reference → [Research Catalog](../reference/research/catalog.md)
- Reference → API → [Research Utilities](../reference/api/research.md)
- How‑to → [Research](../how-to/research/efficiency-workflows.md)
