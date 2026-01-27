import dataclasses
import math
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest

from pollux.config import FrozenConfig
from pollux.core.models import APITier
from pollux.research.efficiency import EfficiencyReport, compare_efficiency
from pollux.types import ResultEnvelope, make_execution_options


def _env(
    *,
    status: str = "ok",
    tokens: int = 0,
    n_calls: Any | None = None,
    durations: dict[str, Any] | None = None,
    per_call_meta: list[dict[str, Any]] | None = None,
) -> ResultEnvelope:
    """Construct a minimal, typed ResultEnvelope for tests.

    Loosens metric value types intentionally to exercise robustness paths.
    """
    env: ResultEnvelope = {
        "status": cast("Literal['ok', 'partial', 'error']", status),
        "answers": [],
        "extraction_method": "unit-test",
        "confidence": 1.0,
        "usage": {"total_token_count": tokens},
        "metrics": {},
    }
    metrics: dict[str, Any] = {}
    if n_calls is not None:
        metrics["vectorized_n_calls"] = n_calls
    if durations is not None:
        metrics["durations"] = durations
    if per_call_meta is not None:
        metrics["per_call_meta"] = per_call_meta
    if metrics:
        env["metrics"] = metrics
    return env


@pytest.mark.unit
def test_efficiency_report_summary_and_verbose_ascii():
    rep = EfficiencyReport(
        status="ok",
        vectorized=_env(tokens=10),
        naive=(
            _env(tokens=5),
            _env(tokens=6),
        ),
        vec_tokens=10,
        vec_time_s=1.0,
        vec_requests=2,
        naive_tokens=11,
        naive_time_s=2.0,
        naive_requests=3,
        tokens_ratio=11 / 10,
        time_ratio=2.0,
        call_ratio=1.5,
        prompt_count=2,
        source_count=0,
        # Trial stats present to exercise verbose path
        vec_time_mean_s=1.2,
        vec_time_p95_s=1.5,
        naive_time_mean_s=2.4,
        naive_time_p95_s=3.0,
        time_ratio_mean=2.0,
        time_ratio_p95=2.5,
    )

    s = rep.summary(verbose=True, ascii_only=True)
    assert "tokens x1.10" in s
    assert "time x2.00" in s
    assert "calls x1.50" in s
    # Verbose trial stats section is present
    assert "[trials" in s and "mean x2.00" in s and "p95 x2.50" in s

    # Infinity formatting check
    rep_inf = dataclasses.replace(rep, time_ratio=math.inf)
    assert "time inf" in rep_inf.summary(ascii_only=True)
    assert "time ∞" in rep_inf.summary(ascii_only=False)


@pytest.mark.unit
def test_efficiency_report_to_dict_safe_and_include_envelopes():
    rep = EfficiencyReport(
        status="ok",
        vectorized=_env(tokens=0),
        naive=(_env(tokens=0),),
        vec_tokens=0,
        vec_time_s=0.0,
        vec_requests=0,
        naive_tokens=0,
        naive_time_s=0.0,
        naive_requests=0,
        # Exercise NaN and +/-Infinity handling
        tokens_ratio=math.inf,
        time_ratio=math.nan,
        call_ratio=1.0,
        prompt_count=1,
        source_count=0,
        time_saved_s=math.inf,
        # Include p95/means to touch _safe for nested fields
        vec_time_mean_s=1.0,
        vec_time_p95_s=math.inf,
        naive_time_mean_s=math.nan,
        naive_time_p95_s=-math.inf,
        vec_pipeline_s=None,
        naive_pipeline_mean_s=0.5,
        naive_pipeline_p95_s=math.nan,
        vec_call_duration_mean_s=math.inf,
        vec_call_duration_p95_s=-math.inf,
        naive_call_duration_mean_s=math.nan,
        naive_call_duration_p95_s=0.1,
    )

    d = rep.to_dict(include_envelopes=True)
    assert d["schema_version"] == 1
    assert d["ratios"]["tokens"] == "Infinity"
    assert d["ratios"]["time"] is None
    assert d["savings"]["time_s"] == "Infinity"
    # Nested fields are sanitized
    assert d["vec"]["time_p95_s"] == "Infinity"
    assert d["naive"]["time_mean_s"] is None
    assert d["naive"]["time_p95_s"] == "-Infinity"
    # Envelopes included
    assert d["vectorized_envelope"]["usage"]["total_token_count"] == 0
    assert isinstance(d["naive_envelopes"], list) and len(d["naive_envelopes"]) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compare_efficiency_sequential_with_pipeline_metrics(monkeypatch):
    # Fake run_batch that distinguishes vectorized vs naive by prompt count
    async def fake_run_batch(prompts, _sources, **_kwargs):
        if len(prompts) > 1:
            return _env(
                status="ok",
                tokens=10,
                n_calls=2,
                durations={"stage1": 0.1, "stage2": 0.2},
                per_call_meta=[{"duration_s": 0.05}, {"duration_s": 0.07}],
            )
        # naive envelope per prompt
        return _env(
            status="ok",
            tokens=7,
            n_calls=1,
            durations={"stage1": 0.1, "stage2": 0.2},
            per_call_meta=[{"duration_s": 0.01}, {"duration_s": 0.02}],
        )

    monkeypatch.setattr("pollux.research.efficiency.run_batch", fake_run_batch)

    # Config resolution for env capture; avoid dataclasses.replace path by leaving cfg=None
    def fake_resolve_config(*_args, **_kwargs):
        return SimpleNamespace(
            model="m",
            provider="p",
            tier="t",
            use_real_api=False,
            enable_caching=True,
            ttl_seconds=0,
            telemetry_enabled=False,
            request_concurrency=3,
        )

    monkeypatch.setattr(
        "pollux.research.efficiency.resolve_config", fake_resolve_config
    )

    # Stable version string
    monkeypatch.setattr(
        "pollux.research.efficiency.importlib_metadata.version",
        lambda _: "0.0-test",
    )

    prompts = ["a", "b", "c"]
    rep = await compare_efficiency(
        prompts,
        sources=(),
        concurrency=None,
        naive_concurrency=None,  # defaults to sequential (1)
        include_pipeline_durations=True,
        label="unit-seq",
        mode="batch",
    )

    # Aggregates
    assert rep.vec_tokens == 10
    assert rep.naive_tokens == 21
    assert rep.tokens_ratio == pytest.approx(2.1, rel=1e-6)
    assert rep.calls_saved == 1 and rep.vec_requests == 2 and rep.naive_requests == 3
    # Pipeline metrics
    assert rep.vec_pipeline_s == pytest.approx(0.3, rel=1e-6)
    assert rep.naive_pipeline_mean_s == pytest.approx(0.3, rel=1e-6)
    assert rep.vec_call_duration_mean_s == pytest.approx((0.05 + 0.07) / 2, rel=1e-6)
    assert rep.naive_call_duration_mean_s == pytest.approx((0.01 + 0.02) / 2, rel=1e-6)
    # Env capture
    d = rep.to_dict()
    assert d["env"]["version"] == "0.0-test"
    assert d["env"]["naive_concurrency_effective"] == 3
    assert d["env"]["vec_concurrency_effective"] == 3  # from config fallback


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compare_efficiency_concurrent_trials_and_status(monkeypatch):
    # Fake run_batch where a specific prompt yields an error in naive path
    async def fake_run_batch(prompts, _sources, **_kwargs):
        if len(prompts) > 1:
            # Vectorized success
            return _env(status="ok", tokens=100, n_calls=4)
        # Naive per prompt: mark one prompt as error
        p = prompts[0]
        status = "error" if p == "ERR" else "ok"
        return _env(status=status, tokens=40, n_calls=1)

    monkeypatch.setattr("pollux.research.efficiency.run_batch", fake_run_batch)

    # Options-based concurrency
    opts = make_execution_options(request_concurrency=5)

    # Trials>1 to exercise mean/p95 computation
    rep = await compare_efficiency(
        ["X", "ERR", "Y"],
        options=opts,
        trials=3,
        warmup=1,
        include_pipeline_durations=False,
        mode="batch",
    )

    # Status should be partial (vectorized ok, at least one naive error)
    assert rep.status == "partial"
    # Effective concurrency derived from options
    assert rep.to_dict()["env"]["naive_concurrency_effective"] == 5
    # Trial stats populated
    assert rep.vec_time_mean_s is not None
    assert rep.naive_time_mean_s is not None

    # If vectorized itself errors, status should be error
    async def fake_run_batch_vec_error(prompts, _sources, **_kwargs):
        if len(prompts) > 1:
            return _env(status="error", tokens=0, n_calls=0)
        return _env(status="ok", tokens=1, n_calls=1)

    monkeypatch.setattr(
        "pollux.research.efficiency.run_batch", fake_run_batch_vec_error
    )
    rep2 = await compare_efficiency(["a", "b"], mode="batch")  # explicit
    assert rep2.status == "error"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mode_aggregate_joins_and_propagates_prefer_json(monkeypatch):
    captured: dict[str, Any] = {"first_prompts": None, "first_prefer_json": None}

    async def fake_run_batch(prompts, _sources, **kwargs):
        if captured["first_prompts"] is None:
            captured["first_prompts"] = tuple(prompts)
            captured["first_prefer_json"] = kwargs.get("prefer_json")
        return _env(status="ok", tokens=9, n_calls=1)

    monkeypatch.setattr("pollux.research.efficiency.run_batch", fake_run_batch)

    prompts = ["Q1?", "Q2?", "Q3?"]
    rep = await compare_efficiency(
        prompts,
        sources=(),
        prefer_json=True,
        mode="aggregate",
    )

    assert isinstance(captured["first_prompts"], tuple)
    assert len(captured["first_prompts"]) == 1
    joined: str = captured["first_prompts"][0]
    assert "compact JSON array of exactly 3 items" in joined
    assert "1. Q1?" in joined and "2. Q2?" in joined and "3. Q3?" in joined
    assert captured["first_prefer_json"] is True
    data = rep.to_dict()
    assert data["env"]["mode"] == "aggregate"
    assert data["env"]["vec_mode_effective"] == "aggregate"
    assert "[mode=aggregate]" in rep.summary(ascii_only=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mode_auto_switches_based_on_prompt_count(monkeypatch):
    calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    async def fake_run_batch(prompts, _sources, **kwargs):
        calls.append((tuple(prompts), kwargs))
        return _env(status="ok", tokens=len(prompts), n_calls=1)

    monkeypatch.setattr("pollux.research.efficiency.run_batch", fake_run_batch)

    # Multi-prompt -> aggregate
    rep_multi = await compare_efficiency(["A", "B"], mode="auto", prefer_json=False)
    prompts_vec_multi = calls[0][0]
    assert len(prompts_vec_multi) == 1  # aggregated
    d_multi = rep_multi.to_dict()
    assert d_multi["env"]["mode"] == "auto"
    assert d_multi["env"]["vec_mode_effective"] == "aggregate"
    assert rep_multi.vec_mode == "aggregate"
    assert "[mode=aggregate]" in rep_multi.summary()

    # Single prompt -> batch
    calls.clear()
    rep_single = await compare_efficiency(["Only"], mode="auto")
    prompts_vec_single = calls[0][0]
    assert len(prompts_vec_single) == 1 and prompts_vec_single[0] == "Only"
    d_single = rep_single.to_dict()
    assert d_single["env"]["vec_mode_effective"] == "batch"
    assert rep_single.vec_mode == "batch"
    assert "[mode=batch]" in rep_single.summary()


@pytest.mark.unit
def test_efficiency_report_summary_handles_nan_ratios():
    rep = EfficiencyReport(
        status="ok",
        vectorized=_env(tokens=0),
        naive=(_env(tokens=0),),
        vec_tokens=0,
        vec_time_s=1.0,
        vec_requests=1,
        naive_tokens=0,
        naive_time_s=1.0,
        naive_requests=1,
        tokens_ratio=math.nan,
        time_ratio=1.0,
        call_ratio=1.0,
        prompt_count=1,
        source_count=0,
    )
    s = rep.summary()
    assert "tokens n/a" in s


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compare_efficiency_vectorized_exception_triggers_error_envelope(
    monkeypatch,
):
    # Vectorized raises, naive ok -> overall error
    async def fake_run_batch(prompts, _sources, **_kwargs):
        if len(prompts) > 1:
            raise RuntimeError("boom")
        return _env(status="ok", tokens=3, n_calls=1)

    monkeypatch.setattr("pollux.research.efficiency.run_batch", fake_run_batch)
    rep = await compare_efficiency(
        ["a", "b"], include_pipeline_durations=False, mode="batch"
    )
    assert rep.status == "error"
    assert rep.vectorized["status"] == "error"
    assert rep.vectorized.get("extraction_method") == "compare_efficiency:vectorized"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_uncached_fallbacks_with_cfg_and_without_cfg(monkeypatch):
    captured_cfgs: list[Any] = []

    async def fake_run_batch(_prompts, _sources, **kwargs):
        captured_cfgs.append(kwargs.get("cfg"))
        return _env(status="ok", tokens=1, n_calls=1)

    monkeypatch.setattr("pollux.research.efficiency.run_batch", fake_run_batch)

    # Case A: cfg provided but dataclasses.replace fails -> fallback to original cfg
    # Use a well-typed FrozenConfig and patch dataclasses.replace to raise
    cfg_obj = FrozenConfig(
        model="m",
        api_key=None,
        use_real_api=False,
        enable_caching=True,
        ttl_seconds=0,
        telemetry_enabled=False,
        tier=APITier.FREE,
        provider="p",
        extra={},
        request_concurrency=3,
    )

    # mypy: help it see a callable with precise signature
    def _raise_replace(obj: FrozenConfig, **kwargs: Any) -> FrozenConfig:  # noqa: ARG001
        raise RuntimeError("replace-fail")

    monkeypatch.setattr(dataclasses, "replace", _raise_replace)
    await compare_efficiency(["p"], cfg=cfg_obj, ensure_uncached=True)
    assert captured_cfgs[-1] is cfg_obj

    # Case B: cfg None and resolve_config raises -> eff_cfg stays None
    def bad_resolve_config(*args, **kwargs):  # noqa: ARG001 - required signature
        raise RuntimeError("fail")

    monkeypatch.setattr("pollux.research.efficiency.resolve_config", bad_resolve_config)
    await compare_efficiency(["p"], cfg=None, ensure_uncached=True)
    assert captured_cfgs[-1] is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parallel_naive_branch_and_robust_metric_parsing(monkeypatch):
    # Setup to trigger parallel naive path and various error-handling branches
    async def fake_run_batch(prompts, _sources, **_kwargs):
        if len(prompts) > 1:
            # Vectorized env with problematic metrics to exercise _tok/_req and metrics parsing
            return {
                "status": "ok",
                "usage": {"total_token_count": "bad"},  # int() raises -> fallback 0
                # metrics not a dict -> outer except path in _sum_durs and _collect_call_durs
                "metrics": "broken",
            }
        # Naive: valid tokens but durations include invalid values to hit continue branch
        return _env(
            status="ok",
            tokens=4,
            n_calls="oops",  # int() raises -> fallback 1 in _req
            durations={"good": 0.2, "bad": "x"},  # ValueError -> continue
            per_call_meta=[{"duration_s": 0.03}, {"duration_s": 0.01}],
        )

    monkeypatch.setattr("pollux.research.efficiency.run_batch", fake_run_batch)

    rep = await compare_efficiency(
        ["a", "b", "c"],
        naive_concurrency=3,  # triggers parallel path (Semaphore + gather)
        include_pipeline_durations=True,
        mode="batch",
    )

    # Check that fallbacks engaged as expected
    assert rep.vec_tokens == 0  # from bad tokens value
    assert rep.vec_requests == 1  # from bad vectorized_n_calls value
    # vec_pipeline_s is None due to outer exception on durations
    assert rep.vec_pipeline_s is None
    # naive pipeline mean computed skipping invalid value
    assert rep.naive_pipeline_mean_s == pytest.approx(0.2, rel=1e-6)
    # call duration means computed
    assert rep.naive_call_duration_mean_s == pytest.approx((0.03 + 0.01) / 2, rel=1e-6)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_eff_vec_concurrency_from_param(monkeypatch):
    async def fake_run_batch(_prompts, _sources, **_kwargs):
        return _env(status="ok", tokens=1, n_calls=2)

    monkeypatch.setattr("pollux.research.efficiency.run_batch", fake_run_batch)
    rep = await compare_efficiency(["q1", "q2"], concurrency=7)
    assert rep.to_dict()["env"]["vec_concurrency_effective"] == 7


@pytest.mark.unit
@pytest.mark.asyncio
async def test_eff_vec_concurrency_config_int_cast_error(monkeypatch):
    class BadInt:
        def __int__(self):
            raise TypeError("no int")

    async def fake_run_batch():
        return _env(status="ok", tokens=1, n_calls=1)

    monkeypatch.setattr("pollux.research.efficiency.run_batch", fake_run_batch)

    def cfg_with_bad_conc() -> Any:
        # Intentionally return a dynamic object to exercise int() cast error path
        return SimpleNamespace(request_concurrency=BadInt())

    # Ensure mypy sees a typed callable while keeping dynamic return at runtime
    def typed_resolve(*_args: Any, **_kwargs: Any) -> Any:
        return cfg_with_bad_conc()

    monkeypatch.setattr(
        "pollux.research.efficiency.resolve_config",
        typed_resolve,
    )

    rep = await compare_efficiency(["only"], concurrency=None, options=None)
    assert rep.to_dict()["env"]["vec_concurrency_effective"] is None
