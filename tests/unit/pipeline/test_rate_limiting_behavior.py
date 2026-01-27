import pytest

from pollux.config import resolve_config
from pollux.core.types import InitialCommand, ResolvedCommand, Success
from pollux.executor import create_executor
from pollux.pipeline.planner import ExecutionPlanner
from pollux.pipeline.rate_limit_handler import RateLimitHandler


@pytest.mark.unit
@pytest.mark.asyncio
async def test_planner_omits_rate_constraint_in_dry_mode_and_sets_in_real_mode():
    # Dry mode (use_real_api=False) → no rate constraint
    cfg_dry = resolve_config(overrides={"use_real_api": False})
    initial_dry = InitialCommand(
        sources=(), prompts=("hello",), config=cfg_dry, history=()
    )
    resolved_dry = ResolvedCommand(initial=initial_dry, resolved_sources=())
    planner = ExecutionPlanner()
    res_dry = await planner.handle(resolved_dry)
    assert isinstance(res_dry, Success)
    plan_dry = res_dry.value.execution_plan
    assert plan_dry.rate_constraint is None

    # Real mode (use_real_api=True) → constraint present (model + tier known by default)
    cfg_real = resolve_config(overrides={"use_real_api": True, "api_key": "dummy"})
    initial_real = InitialCommand(
        sources=(), prompts=("hello",), config=cfg_real, history=()
    )
    resolved_real = ResolvedCommand(initial=initial_real, resolved_sources=())
    res_real = await planner.handle(resolved_real)
    assert isinstance(res_real, Success)
    plan_real = res_real.value.execution_plan
    assert plan_real.rate_constraint is not None
    assert plan_real.rate_constraint.requests_per_minute > 0


@pytest.mark.unit
def test_executor_pipeline_always_includes_rate_limiter():
    # Pipeline includes RateLimitHandler for both dry and real modes.
    # Enforcement is plan-driven via ExecutionPlan.rate_constraint.
    cfg_dry = resolve_config(overrides={"use_real_api": False})
    exec_dry = create_executor(cfg_dry)
    assert any(isinstance(h, RateLimitHandler) for h in exec_dry._pipeline)

    cfg_real = resolve_config(overrides={"use_real_api": True, "api_key": "dummy"})
    exec_real = create_executor(cfg_real)
    assert any(isinstance(h, RateLimitHandler) for h in exec_real._pipeline)
