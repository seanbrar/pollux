import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    FinalizedCommand,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    Source,
    TextPart,
    TokenEstimate,
)
from pollux.pipeline.api_handler import APIHandler

pytestmark = pytest.mark.unit


def make_planned_with_estimate(prompt_text: str, expected: int) -> PlannedCommand:
    initial = InitialCommand(
        sources=(Source.from_text("test content"),),
        prompts=(prompt_text,),
        config=resolve_config(overrides={"api_key": "k"}),
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    call = APICall(
        model_name="gemini-2.0-flash",
        api_parts=(TextPart(text=prompt_text),),
        api_config={},
    )
    plan = ExecutionPlan(calls=(call,))
    # Give an estimate that should be reflected in usage.total_token_count approximately
    estimate = TokenEstimate(
        min_tokens=max(expected - 5, 0),
        expected_tokens=expected,
        max_tokens=expected + 10,
        confidence=0.8,
    )
    return PlannedCommand(
        resolved=resolved, execution_plan=plan, token_estimate=estimate
    )


@pytest.mark.asyncio
async def test_api_handler_simulated_usage_matches_estimate_envelope():
    handler = APIHandler()
    # Use a realistic estimate that matches mock adapter calculation
    # Mock adapter calculates: max(len(text) // 4 + 10, 0) = 12 for "hello world"
    planned = make_planned_with_estimate("hello world", expected=12)
    result = await handler.handle(planned)
    from pollux.core.types import Success

    assert isinstance(result, Success)
    finalized: FinalizedCommand = result.value
    usage = finalized.telemetry_data.get("usage", {})
    assert isinstance(usage, dict)
    total = usage.get("total_token_count")
    assert isinstance(total, int)
    assert planned.token_estimate is not None
    assert (
        planned.token_estimate.min_tokens <= total <= planned.token_estimate.max_tokens
    )
