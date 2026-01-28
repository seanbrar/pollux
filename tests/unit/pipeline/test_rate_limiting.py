from unittest.mock import Mock, patch

import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    InitialCommand,
    PlannedCommand,
    RateConstraint,
    ResolvedCommand,
    Success,
    TextPart,
)
from pollux.executor import create_executor
from pollux.pipeline.planner import ExecutionPlanner
from pollux.pipeline.rate_limit_handler import RateLimitHandler

pytestmark = pytest.mark.unit


def _planned_with_constraint(rpm: int, tpm: int | None = None) -> PlannedCommand:
    initial = Mock()
    cfg = Mock()
    cfg.model = "gemini-2.0-flash"
    cfg.tier = Mock()
    initial.config = cfg
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    call = APICall(
        model_name="gemini-2.0-flash", api_parts=(TextPart("hi"),), api_config={}
    )
    plan = ExecutionPlan(calls=(call,), rate_constraint=RateConstraint(rpm, tpm))
    return PlannedCommand(resolved=resolved, execution_plan=plan)


class TestRateLimitingLogic:
    """Tests for the RateLimitHandler logic and enforcement."""

    @pytest.mark.asyncio
    async def test_passthrough_without_constraint(self):
        handler = RateLimitHandler()
        initial = Mock()
        cfg = Mock()
        cfg.model = "gemini-2.0-flash"
        cfg.tier = Mock()
        initial.config = cfg
        resolved = ResolvedCommand(initial=initial, resolved_sources=())
        call = APICall(
            model_name="gemini-2.0-flash", api_parts=(TextPart("hi"),), api_config={}
        )
        plan = ExecutionPlan(calls=(call,), rate_constraint=None)
        cmd = PlannedCommand(resolved=resolved, execution_plan=plan)

        result = await handler.handle(cmd)
        assert isinstance(result, Success)
        assert result.value is cmd

    @pytest.mark.asyncio
    async def test_request_delay_enforced_with_mocked_clock(self):
        # Simulate second request at time 0 with rpm=60 → expect 1s sleep
        times = [0.0, 0.0, 0.0]
        clock = Mock(side_effect=times)
        handler = RateLimitHandler(clock=clock)
        cmd = _planned_with_constraint(rpm=60)

        with patch("asyncio.sleep") as sleep_mock:
            # First pass: no wait (initial last_time=0)
            await handler.handle(cmd)
            # Second pass: should wait ~1.0s
            await handler.handle(cmd)
            assert sleep_mock.called

    @pytest.mark.asyncio
    async def test_token_delay_enforced_with_mocked_clock(self):
        # For tpm=120 and estimated tokens=60, required ~30s → ensure a sleep occurs
        times = [0.0, 0.0, 0.0]
        clock = Mock(side_effect=times)
        handler = RateLimitHandler(clock=clock)
        cmd = _planned_with_constraint(rpm=1000, tpm=120)
        object.__setattr__(cmd, "token_estimate", Mock(max_tokens=60))

        with patch("asyncio.sleep") as sleep_mock:
            await handler.handle(cmd)
            assert sleep_mock.called

    def test_key_extractor_normalizes_tier_enum_or_string(self):
        handler = RateLimitHandler()

        # Case 1: tier as enum-like object with .value
        enum_like = Mock()
        enum_like.value = "free"
        initial1 = Mock()
        cfg1 = Mock()
        cfg1.model = "gemini-2.0-flash"
        cfg1.tier = enum_like
        initial1.config = cfg1
        resolved1 = ResolvedCommand(initial=initial1, resolved_sources=())
        call1 = APICall(
            model_name="gemini-2.0-flash", api_parts=(TextPart("hi"),), api_config={}
        )
        plan1 = ExecutionPlan(calls=(call1,))
        cmd1 = PlannedCommand(resolved=resolved1, execution_plan=plan1)
        key1 = handler._default_key_extractor(cmd1)
        assert key1[2] == "free"

        # Case 2: tier as plain string
        initial2 = Mock()
        cfg2 = Mock()
        cfg2.model = "gemini-2.0-flash"
        cfg2.tier = "tier_1"
        initial2.config = cfg2
        resolved2 = ResolvedCommand(initial=initial2, resolved_sources=())
        call2 = APICall(
            model_name="gemini-2.0-flash", api_parts=(TextPart("hi"),), api_config={}
        )
        plan2 = ExecutionPlan(calls=(call2,))
        cmd2 = PlannedCommand(resolved=resolved2, execution_plan=plan2)
        key2 = handler._default_key_extractor(cmd2)
        assert key2[2] == "tier_1"


class TestRateLimitingIntegration:
    """Tests for rate limiting integration within the pipeline."""

    @pytest.mark.asyncio
    async def test_planner_omits_rate_constraint_in_dry_mode_and_sets_in_real_mode(
        self,
    ):
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

        # Real mode (use_real_api=True) → constraint present
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

    def test_executor_pipeline_always_includes_rate_limiter(self):
        # Pipeline includes RateLimitHandler for both dry and real modes.
        cfg_dry = resolve_config(overrides={"use_real_api": False})
        exec_dry = create_executor(cfg_dry)
        assert any(isinstance(h, RateLimitHandler) for h in exec_dry._pipeline)

        cfg_real = resolve_config(overrides={"use_real_api": True, "api_key": "dummy"})
        exec_real = create_executor(cfg_real)
        assert any(isinstance(h, RateLimitHandler) for h in exec_real._pipeline)
