"""Efficiency comparison helper: vectorized vs naive execution.

This module provides helpers intended for research/benchmarking workflows.
It is intentionally separate from scenario-first helpers in `frontdoor.py`.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import importlib.metadata as importlib_metadata
import math
import os
import platform
import sys
import time
from typing import TYPE_CHECKING, Any, Literal

from pollux.config import resolve_config
from pollux.frontdoor import run_batch

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Iterable

    from pollux.config import FrozenConfig
    from pollux.core.execution_options import ExecutionOptions
    from pollux.core.types import Source
    from pollux.types import ResultEnvelope


@dataclasses.dataclass(frozen=True)
class EfficiencyReport:
    """Compact comparison of vectorized vs naive execution.

    Fields:
        status: Overall health of both paths (ok | partial | error).
        vectorized: ResultEnvelope from a single vectorized run over prompts.
        naive: Tuple of ResultEnvelopes from one-call-per-prompt.
        vec_tokens/vec_time_s/vec_requests: Aggregates for vectorized path.
        naive_tokens/naive_time_s/naive_requests: Aggregates for naive path.
        tokens_ratio/time_ratio: baseline/total; higher is better.
        prompt_count/source_count: Inputs cardinality for clarity.
    """

    status: Literal["ok", "partial", "error"]
    vectorized: ResultEnvelope
    naive: tuple[ResultEnvelope, ...]
    vec_tokens: int
    vec_time_s: float
    vec_requests: int
    naive_tokens: int
    naive_time_s: float
    naive_requests: int
    tokens_ratio: float
    time_ratio: float
    call_ratio: float
    prompt_count: int
    source_count: int
    # Optional pipeline timing view (enabled via include_pipeline_durations)
    vec_pipeline_s: float | None = None
    naive_pipeline_mean_s: float | None = None
    naive_pipeline_p95_s: float | None = None
    # Optional per-call duration distribution (from metrics.per_call_meta)
    vec_call_duration_mean_s: float | None = None
    vec_call_duration_p95_s: float | None = None
    naive_call_duration_mean_s: float | None = None
    naive_call_duration_p95_s: float | None = None
    # Optional label to tag this comparison run
    label: str | None = None
    # Convenience savings fields
    tokens_saved: int = 0
    time_saved_s: float = 0.0
    calls_saved: int = 0
    # Effective vectorized execution shape (for observability)
    vec_mode: Literal["batch", "aggregate"] | None = None
    # Optional trial statistics (present when trials > 1)
    vec_time_mean_s: float | None = None
    vec_time_p95_s: float | None = None
    naive_time_mean_s: float | None = None
    naive_time_p95_s: float | None = None
    time_ratio_mean: float | None = None
    time_ratio_p95: float | None = None
    # Environment capture for reproducibility
    env: dict[str, Any] = dataclasses.field(default_factory=dict)
    # Schema version for downstream consumers
    schema_version: int = 1

    def summary(self, *, verbose: bool = False, ascii_only: bool = False) -> str:
        """Return a one-line human summary for logs and dashboards.

        Args:
            verbose: When True, append mean/p95 timing when available (trials > 1).
            ascii_only: When True, use ASCII-only symbols (e.g., 'inf' instead of '∞').
        """

        def _fmt_ratio(x: float) -> str:
            if math.isnan(x):
                return "n/a"
            if math.isinf(x):
                return "inf" if ascii_only else "∞"
            return f"x{x:.2f}"

        tok = _fmt_ratio(self.tokens_ratio)
        tim = _fmt_ratio(self.time_ratio)
        calls = _fmt_ratio(self.call_ratio)
        base = (
            f"tokens {tok} (saved {self.tokens_saved}), time {tim} (saved {self.time_saved_s:.3f}s), calls {calls} (saved {self.calls_saved}) "
            f"(prompts={self.prompt_count}, sources={self.source_count}, "
            f"reqs: vec={self.vec_requests}, naive={self.naive_requests})"
        )

        if (
            verbose
            and self.vec_time_mean_s is not None
            and self.naive_time_mean_s is not None
        ):
            # Prefer trial-level time ratio stats when present
            tr_mean = self.time_ratio_mean
            tr_p95 = self.time_ratio_p95
            tr_mean_s = (
                f", mean {_fmt_ratio(tr_mean)}"
                if tr_mean is not None and math.isfinite(tr_mean)
                else ""
            )
            tr_p95_s = (
                f", p95 {_fmt_ratio(tr_p95)}"
                if tr_p95 is not None and math.isfinite(tr_p95)
                else ""
            )
            base = base + f" [trials{tr_mean_s}{tr_p95_s}]"
        # Append effective mode when available for quick scans
        if self.vec_mode:
            return base + f" [mode={self.vec_mode}]"
        return base

    def to_dict(self, *, include_envelopes: bool = False) -> dict[str, Any]:
        """Return a JSON-logging-friendly dict representation.

        Args:
            include_envelopes: When True, include the raw `vectorized` envelope
                and the list of `naive` envelopes. Defaults to False to keep
                logs compact.
        """

        def _safe(x: float | None) -> float | str | None:
            if x is None:
                return None
            if math.isfinite(x):
                return float(x)
            if math.isnan(x):
                return None
            return "Infinity" if x > 0 else "-Infinity"

        data: dict[str, Any] = {
            "schema_version": int(self.schema_version),
            "label": self.label,
            "status": self.status,
            "vec_mode": self.vec_mode,
            "prompt_count": self.prompt_count,
            "source_count": self.source_count,
            "env": dict(self.env),
            "vec": {
                "tokens": self.vec_tokens,
                "time_s": self.vec_time_s,
                "time_mean_s": _safe(getattr(self, "vec_time_mean_s", None)),
                "time_p95_s": _safe(getattr(self, "vec_time_p95_s", None)),
                "requests": self.vec_requests,
                "pipeline_s": _safe(self.vec_pipeline_s),
                "call_duration_mean_s": _safe(self.vec_call_duration_mean_s),
                "call_duration_p95_s": _safe(self.vec_call_duration_p95_s),
            },
            "naive": {
                "tokens": self.naive_tokens,
                "time_s": self.naive_time_s,
                "time_mean_s": _safe(getattr(self, "naive_time_mean_s", None)),
                "time_p95_s": _safe(getattr(self, "naive_time_p95_s", None)),
                "requests": self.naive_requests,
                "pipeline_mean_s": _safe(self.naive_pipeline_mean_s),
                "pipeline_p95_s": _safe(self.naive_pipeline_p95_s),
                "call_duration_mean_s": _safe(self.naive_call_duration_mean_s),
                "call_duration_p95_s": _safe(self.naive_call_duration_p95_s),
            },
            "ratios": {
                "tokens": _safe(self.tokens_ratio),
                "time": _safe(self.time_ratio),
                "time_mean": _safe(getattr(self, "time_ratio_mean", None)),
                "time_p95": _safe(getattr(self, "time_ratio_p95", None)),
                "calls": _safe(self.call_ratio),
            },
            "savings": {
                "tokens": int(self.tokens_saved),
                "time_s": _safe(self.time_saved_s),
                "calls": int(self.calls_saved),
            },
        }
        if include_envelopes:
            data["vectorized_envelope"] = self.vectorized
            data["naive_envelopes"] = list(self.naive)
        return data


async def compare_efficiency(
    prompts: Iterable[str] | str,
    sources: Iterable[Source] = (),
    *,
    cfg: FrozenConfig | None = None,
    options: ExecutionOptions | None = None,
    prefer_json: bool | None = None,
    concurrency: int | None = None,
    naive_concurrency: int | None = None,
    include_pipeline_durations: bool = False,
    label: str | None = None,
    trials: int = 1,
    warmup: int = 0,
    ensure_uncached: bool = False,
    mode: Literal["batch", "aggregate", "auto"] = "auto",
    aggregate_prompt_builder: Callable[[list[str]], str] | None = None,
) -> EfficiencyReport:
    """Compare vectorized execution vs naive one-call-per-prompt.

    Runs the same workload two ways:
      (A) Vectorized once via run_batch(prompts, sources)
      (B) Naive N calls, one per prompt, same sources

    Returns both paths' ResultEnvelopes alongside aggregate tokens/time and
    improvement ratios (baseline/total). Ratios > 1 indicate the vectorized
    path used fewer tokens or less time than the naive baseline. Request counts
    are derived from `metrics.vectorized_n_calls` when present.

    Vectorized `mode`:
      - "auto" (default): choose "aggregate" when there is more than one prompt;
        otherwise use "batch".
      - "batch": pass all prompts to `run_batch` as-is. The pipeline
        may still perform multiple provider requests internally (e.g., chunking),
        but the prompts remain independent.
      - "aggregate": join multiple prompts into a single instruction asking the
        model to answer each prompt and return a JSON array of answers. This
        emphasizes token-economics when large shared context dominates and a
        single provider call can process that context once.

    Notes for "aggregate": Prefer structured outputs (`prefer_json=True`) for
    most reliable parsing of multi-answer responses. When the effective mode is
    aggregate and `prefer_json` is not provided, this helper implicitly sets
    it to True for robustness and records it in the environment.

    Warm-up note:
      - If measurements vary widely on first run, consider a short warm-up
        call that mirrors inputs (e.g., same sources, small prompts) prior to
        invoking this helper. This can mitigate cold starts (adapter/process
        init), lazy filesystem work, or cache population. Prefer warming both
        vectorized and naive shapes similarly for fair comparisons.

    Concurrency notes:
      - `concurrency` (vectorized only): bounds client-side fan-out when the
        vectorized pipeline performs multiple requests (e.g., chunked calls);
        mirrors `ExecutionOptions.request_concurrency`.
      - `naive_concurrency` (naive only): bounds fan-out across per-prompt
        calls in the naive baseline. Defaults to match `concurrency` (parity)
        if provided, otherwise sequential (1). Override to intentionally test
        parallel naive vs sequential vectorized, or vice-versa.
    """
    # Eagerly materialize inputs to avoid generator exhaustion and ensure
    # parity of inputs across both paths.
    prompt_list: list[str] = (
        [prompts] if isinstance(prompts, str) else [str(p) for p in prompts]
    )
    source_list: list[Source] = list(sources)

    # Helpers
    def _make_error_envelope(msg: str, *, where: str) -> ResultEnvelope:
        return {
            "status": "error",
            "answers": [],
            "extraction_method": f"compare_efficiency:{where}",
            "confidence": 0.0,
            "diagnostics": {"error": msg},
        }

    def _safe_ratio(num: float, denom: float) -> float:
        try:
            if float(denom) > 0.0:
                return float(num) / float(denom)
            # Undefined when both zero, else infinite improvement
            return float("nan") if float(num) == 0.0 else float("inf")
        except Exception:
            return float("nan")

    # Validate trials & warmup
    trials = max(1, int(trials))
    warmup = max(0, int(warmup))

    # Optional per-call config override to force caching off (simplest, robust)
    eff_cfg: FrozenConfig | None = cfg
    if ensure_uncached:
        try:
            if cfg is not None:
                eff_cfg = dataclasses.replace(cfg, enable_caching=False)
            else:
                eff_cfg = resolve_config(overrides={"enable_caching": False})
        except Exception:
            eff_cfg = cfg

    # Helper to construct strict aggregate instruction
    def _build_aggregate_prompt(items: list[str]) -> str:
        n = len(items)
        header = (
            "Answer each question separately. Return only a compact JSON array of "
            f"exactly {n} items in the same order, with no additional text or explanation.\n\n"
        )
        body = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(items))
        return header + body

    # One trial runner
    async def _run_once() -> tuple[ResultEnvelope, list[ResultEnvelope], float, float]:
        # Vectorized run
        t0 = time.perf_counter()
        try:
            # Decide vectorized execution shape
            def _vec_mode() -> Literal["batch", "aggregate"]:
                if mode == "auto":
                    return "aggregate" if len(prompt_list) > 1 else "batch"
                return mode

            # Effective prefer_json: default to True when aggregating and not explicitly set
            def _effective_prefer_json() -> bool:
                if prefer_json is not None:
                    return bool(prefer_json)
                return _vec_mode() == "aggregate" and len(prompt_list) > 1

            if _vec_mode() == "aggregate" and len(prompt_list) > 1:
                # Architect single-call shape: join questions into one prompt while
                # preserving shared context in `shared_parts`. This yields a single
                # provider call processing the large context once.
                if aggregate_prompt_builder is not None:
                    joined = str(aggregate_prompt_builder(prompt_list))
                else:
                    joined = _build_aggregate_prompt(prompt_list)
                vec_local = await run_batch(
                    (joined,),
                    tuple(source_list),
                    cfg=eff_cfg,
                    options=options,
                    prefer_json=_effective_prefer_json(),
                    concurrency=concurrency,
                )
            else:
                vec_local = await run_batch(
                    tuple(prompt_list),
                    tuple(source_list),
                    cfg=eff_cfg,
                    options=options,
                    prefer_json=_effective_prefer_json(),
                    concurrency=concurrency,
                )
        except Exception as e:  # pragma: no cover - best-effort research helper
            vec_local = _make_error_envelope(str(e), where="vectorized")
        t1 = time.perf_counter()

        # Naive per-prompt calls (defaults to parity with vectorized concurrency)
        naive_envs_local: list[ResultEnvelope] = []
        t2 = time.perf_counter()
        effective_naive_conc = (
            naive_concurrency
            if naive_concurrency is not None
            else (concurrency if concurrency is not None else 1)
        )
        effective_naive_conc = max(1, int(effective_naive_conc))

        if effective_naive_conc <= 1:
            for p in prompt_list:
                try:
                    env = await run_batch(
                        (p,),
                        tuple(source_list),
                        cfg=eff_cfg,
                        options=options,
                        prefer_json=bool(prefer_json)
                        if prefer_json is not None
                        else False,
                        concurrency=concurrency,
                    )
                except Exception as e:  # pragma: no cover
                    env = _make_error_envelope(str(e), where="naive")
                naive_envs_local.append(env)
        else:
            sem = asyncio.Semaphore(effective_naive_conc)

            async def _one(prompt_solo: str) -> ResultEnvelope:
                async with sem:
                    try:
                        return await run_batch(
                            (prompt_solo,),
                            tuple(source_list),
                            cfg=eff_cfg,
                            options=options,
                            prefer_json=bool(prefer_json)
                            if prefer_json is not None
                            else False,
                            concurrency=concurrency,
                        )
                    except Exception as e:  # pragma: no cover
                        return _make_error_envelope(str(e), where="naive")

            gathered_local = await asyncio.gather(*(_one(p) for p in prompt_list))
            naive_envs_local.extend(gathered_local)
        t3 = time.perf_counter()
        return vec_local, naive_envs_local, (t1 - t0), (t3 - t2)

    # Warm-ups
    for _ in range(warmup):
        await _run_once()

    # Trials (record time series; keep envelopes from the first trial)
    vec_time_series: list[float] = []
    naive_time_series: list[float] = []
    vec: ResultEnvelope
    naive_envs: list[ResultEnvelope]
    vec = {}
    naive_envs = []
    for i in range(trials):
        vec_i, naive_i, vt, nt = await _run_once()
        if i == 0:
            vec = vec_i
            naive_envs = naive_i
        vec_time_series.append(vt)
        naive_time_series.append(nt)

    def _tok(env: ResultEnvelope) -> int:
        u = env.get("usage") or {}
        try:
            return int(u.get("total_token_count", 0) or 0)
        except Exception:
            return 0

    vec_tokens = _tok(vec)
    naive_tokens = sum(_tok(e) for e in naive_envs)

    def _req(env: ResultEnvelope) -> int:
        try:
            m = env.get("metrics") or {}
            v = m.get("vectorized_n_calls")
            return int(v) if v is not None else 1
        except Exception:
            return 1

    vec_time = vec_time_series[0]
    naive_time = naive_time_series[0]
    vec_requests = _req(vec)
    naive_requests = sum(_req(e) for e in naive_envs)

    vec_status = vec.get("status", "ok")
    naive_statuses = [e.get("status", "ok") for e in naive_envs]
    status: Literal["ok", "partial", "error"]
    if vec_status == "error" or (
        naive_statuses and all(s == "error" for s in naive_statuses)
    ):
        status = "error"
    elif vec_status != "ok" or any(s != "ok" for s in naive_statuses):
        status = "partial"
    else:
        status = "ok"

    # Optional pipeline durations view
    vec_pipe_s: float | None = None
    naive_pipe_vals: list[float] = []
    vec_call_durs: list[float] = []
    naive_call_durs: list[float] = []
    if include_pipeline_durations:

        def _sum_durs(env: ResultEnvelope) -> float | None:
            try:
                d = env.get("metrics", {}).get("durations")
                if isinstance(d, dict):
                    total = 0.0
                    for v in d.values():
                        try:
                            total += float(v)
                        except (TypeError, ValueError):
                            continue
                    return total
            except Exception:
                return None
            return None

        vec_pipe_s = _sum_durs(vec)
        for env_i in naive_envs:
            s = _sum_durs(env_i)
            if s is not None:
                naive_pipe_vals.append(s)

        # Per-call meta durations (if surfaced by the pipeline)
        def _collect_call_durs(env: ResultEnvelope) -> list[float]:
            try:
                m = env.get("metrics", {})
                pcm = m.get("per_call_meta")
                if isinstance(pcm, list | tuple):
                    vals: list[float] = []
                    for item in pcm:
                        if isinstance(item, dict):
                            with contextlib.suppress(Exception):
                                d = float(item.get("duration_s", 0.0) or 0.0)
                                if d >= 0.0:
                                    vals.append(d)
                    return vals
            except Exception:
                return []
            return []

        vec_call_durs = _collect_call_durs(vec)
        for env_i in naive_envs:
            naive_call_durs.extend(_collect_call_durs(env_i))

    def _p95(xs: list[float]) -> float | None:
        if not xs:
            return None
        ys = sorted(xs)
        idx = int(0.95 * (len(ys) - 1))
        return ys[idx]

    # Trial stats
    vec_time_mean_s = sum(vec_time_series) / len(vec_time_series)
    naive_time_mean_s = sum(naive_time_series) / len(naive_time_series)
    vec_time_p95_s = _p95(vec_time_series)
    naive_time_p95_s = _p95(naive_time_series)
    time_ratio_series = [
        (_safe_ratio(naive_time_series[i], vec_time_series[i])) for i in range(trials)
    ]
    finite_tr = [x for x in time_ratio_series if math.isfinite(x)]
    time_ratio_mean = sum(finite_tr) / len(finite_tr) if finite_tr else float("nan")
    time_ratio_p95 = _p95(finite_tr)

    # Environment capture (best-effort)
    effective_cfg = cfg
    if effective_cfg is None:
        try:
            effective_cfg = resolve_config()
        except Exception:  # pragma: no cover - optional
            effective_cfg = None

    def _eff_vec_conc() -> int | None:
        if concurrency is not None:
            return int(concurrency)
        ropts = getattr(options, "request_concurrency", None)
        if ropts is not None:
            with contextlib.suppress(Exception):
                return int(ropts)
        if effective_cfg is not None:
            try:
                v: Any = getattr(effective_cfg, "request_concurrency", None)
                return int(v) if v is not None else None
            except Exception:
                return None
        return None

    if naive_concurrency is not None:
        eff_naive_val = int(naive_concurrency)
    else:
        _vec_conc = _eff_vec_conc()
        if _vec_conc is not None:
            eff_naive_val = int(_vec_conc)
        elif concurrency is not None:
            eff_naive_val = int(concurrency)
        else:
            eff_naive_val = 1
    effective_naive_conc = max(1, eff_naive_val)

    version: str
    try:
        version = importlib_metadata.version("gemini-batch")
    except importlib_metadata.PackageNotFoundError:  # pragma: no cover - dev
        version = "development"

    # Resolve effective vec mode for observability
    effective_vec_mode: Literal["batch", "aggregate"] = (
        "aggregate"
        if (mode == "aggregate" or (mode == "auto" and len(prompt_list) > 1))
        else "batch"
    )

    # Compute effective prefer_json based on effective mode for env reporting
    prefer_json_effective = (
        bool(prefer_json)
        if prefer_json is not None
        else (effective_vec_mode == "aggregate" and len(prompt_list) > 1)
    )

    env_data: dict[str, Any] = {
        "version": version,
        "prefer_json": bool(prefer_json) if prefer_json is not None else None,
        "prefer_json_effective": prefer_json_effective,
        "trials": trials,
        "warmup": warmup,
        "mode": mode,
        "vec_mode_effective": effective_vec_mode,
        "vec_concurrency_effective": _eff_vec_conc(),
        "naive_concurrency_effective": effective_naive_conc,
        "ensure_uncached": bool(ensure_uncached),
        # Runtime context (best-effort, no shellouts)
        "python_version": sys.version.split(" ")[0],
        "python_impl": platform.python_implementation(),
        "platform": platform.platform(aliased=False, terse=True),
        "os_name": os.name,
        "cpu_count": os.cpu_count(),
        "pid": os.getpid(),
        # CI/git hints via env if provided by the host environment
        "git_sha": os.getenv("GIT_SHA") or os.getenv("GITHUB_SHA"),
        "git_dirty": os.getenv("GIT_DIRTY"),
    }
    if effective_cfg is not None:
        env_data.update(
            {
                "model": getattr(effective_cfg, "model", None),
                "provider": getattr(effective_cfg, "provider", None),
                "tier": getattr(effective_cfg, "tier", None),
                "use_real_api": getattr(effective_cfg, "use_real_api", None),
                "enable_caching": getattr(effective_cfg, "enable_caching", None),
                "ttl_seconds": getattr(effective_cfg, "ttl_seconds", None),
                "telemetry_enabled": getattr(effective_cfg, "telemetry_enabled", None),
                "request_concurrency_default": getattr(
                    effective_cfg, "request_concurrency", None
                ),
            }
        )

    # Optional aggregate count sanity check (best-effort)
    aggregate_expected_answer_count: int | None = None
    aggregate_observed_answer_count: int | None = None
    with contextlib.suppress(Exception):
        if effective_vec_mode == "aggregate":
            aggregate_expected_answer_count = len(prompt_list)
            ans = vec.get("answers")
            if isinstance(ans, list | tuple):
                aggregate_observed_answer_count = len(ans)
    if aggregate_expected_answer_count is not None:
        env_data["aggregate_expected_answer_count"] = aggregate_expected_answer_count
    if aggregate_observed_answer_count is not None:
        env_data["aggregate_observed_answer_count"] = aggregate_observed_answer_count

    return EfficiencyReport(
        status=status,
        vectorized=vec,
        naive=tuple(naive_envs),
        vec_tokens=vec_tokens,
        vec_time_s=float(vec_time),
        vec_requests=vec_requests,
        naive_tokens=naive_tokens,
        naive_time_s=float(naive_time),
        naive_requests=naive_requests,
        tokens_ratio=_safe_ratio(naive_tokens, vec_tokens),
        time_ratio=_safe_ratio(naive_time, vec_time),
        call_ratio=_safe_ratio(naive_requests, vec_requests),
        tokens_saved=int(naive_tokens - vec_tokens),
        time_saved_s=float(naive_time - vec_time),
        calls_saved=int(naive_requests - vec_requests),
        prompt_count=len(prompt_list),
        source_count=len(source_list),
        vec_time_mean_s=float(vec_time_mean_s) if trials > 1 else None,
        vec_time_p95_s=float(vec_time_p95_s)
        if trials > 1 and vec_time_p95_s is not None
        else None,
        naive_time_mean_s=float(naive_time_mean_s) if trials > 1 else None,
        naive_time_p95_s=float(naive_time_p95_s)
        if trials > 1 and naive_time_p95_s is not None
        else None,
        time_ratio_mean=float(time_ratio_mean) if trials > 1 else None,
        time_ratio_p95=float(time_ratio_p95)
        if trials > 1 and time_ratio_p95 is not None
        else None,
        vec_pipeline_s=vec_pipe_s,
        naive_pipeline_mean_s=(sum(naive_pipe_vals) / len(naive_pipe_vals))
        if naive_pipe_vals
        else None,
        naive_pipeline_p95_s=_p95(naive_pipe_vals),
        vec_call_duration_mean_s=(sum(vec_call_durs) / len(vec_call_durs))
        if vec_call_durs
        else None,
        vec_call_duration_p95_s=_p95(vec_call_durs),
        naive_call_duration_mean_s=(sum(naive_call_durs) / len(naive_call_durs))
        if naive_call_durs
        else None,
        naive_call_duration_p95_s=_p95(naive_call_durs),
        label=label,
        env=env_data,
        vec_mode=effective_vec_mode,
    )
