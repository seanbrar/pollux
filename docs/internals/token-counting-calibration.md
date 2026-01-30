# Token Counting Calibration

This deep dive summarizes empirical calibration of token estimation versus actual usage to improve planning safety and cost predictability.

## Executive summary

- Mean estimation drift observed: ~4–8% overestimation on common corpora; higher variance for PDFs and mixed “file” content.
- Targets: ≥95% of real usage within [min, max] bounds; drift skew toward overestimation; median accuracy ratio drift ≤10% across two releases.

## Method (high level)

- Compare the planner’s provider‑aware estimates to actual usage recorded at execution time across varied sources (PDFs, text, mixed media).
- Aggregate ratios and error metrics (mean/median, in‑range %, over/under distribution) and evaluate by content type.

## Findings (high level)

- Text content: consistent, slight overestimation; narrow variance.
- PDFs and generic files: broader variance; occasional underestimation on larger documents.
- Images/video when mapped to generic file types: estimation less stable without MIME‑aware heuristics.

## Recommendations

- Keep estimation pure in the Execution Planner; use provider adapters for heuristics (see ADR‑0002).
- Adjust bias factors conservatively for content types with known variance; prefer small overestimation to underestimation.
- Preserve MIME/type hints where possible to select better heuristics; widen ranges for mixed content.
- Validate continuously with execution telemetry and update bias tables on drift.

## Validation targets

- Coverage: ≥95% of executions fall within predicted [min, max] ranges across evaluation corpora.
- Direction: Misses skew toward overestimation.
- Stability: Median drift remains within target across two releases before updating “latest” bias table alias.

## References

- Concept → Token Counting & Estimation
- Decision → ADR‑0002 Token Counting Model
