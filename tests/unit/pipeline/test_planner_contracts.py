import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    Failure,
    InitialCommand,
    ResolvedCommand,
    Source,
    Success,
)
from pollux.pipeline.planner import ExecutionPlanner

pytestmark = pytest.mark.contract


@pytest.mark.asyncio
async def test_planner_produces_parts_on_prompts():
    planner = ExecutionPlanner()
    initial = InitialCommand(
        sources=(Source.from_text("src content"),),
        prompts=("p1", "p2"),
        config=resolve_config(overrides={"api_key": "k"}),
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    result = await planner.handle(resolved)

    assert isinstance(result, Success)
    planned = result.value
    plan = planned.execution_plan
    # Vectorized path: two independent calls, primary_call mirrors the first call
    assert plan.calls and len(plan.calls) == 2
    first_call = plan.calls[0]
    assert first_call.api_parts and hasattr(first_call.api_parts[0], "text")
    assert first_call.api_parts[0].text == "p1"
    # calls[0] is the primary call in the new API
    assert plan.calls[0].model_name == first_call.model_name
    assert plan.calls[0].api_config == first_call.api_config
    assert plan.calls[0].api_parts == first_call.api_parts


@pytest.mark.asyncio
async def test_planner_fails_on_empty_prompts():
    planner = ExecutionPlanner()
    initial = InitialCommand(
        sources=(Source.from_text("src content"),),
        prompts=(),
        config=resolve_config(overrides={"api_key": "k"}),
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    result = await planner.handle(resolved)

    assert isinstance(result, Failure)
