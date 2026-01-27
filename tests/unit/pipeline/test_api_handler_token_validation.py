from typing import cast

import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    Source,
    Success,
    TextPart,
    TokenEstimate,
)
from pollux.pipeline.api_handler import APIHandler


def _planned_with_estimate(prompt_text: str, expected: int) -> PlannedCommand:
    initial = InitialCommand(
        sources=(Source.from_text("s"),),
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
    estimate = TokenEstimate(
        min_tokens=expected // 2,
        expected_tokens=expected,
        max_tokens=expected * 2,
        confidence=0.8,
    )
    return PlannedCommand(
        resolved=resolved, execution_plan=plan, token_estimate=estimate
    )


@pytest.mark.asyncio
async def test_token_validation_attached_in_mock_path():
    handler = APIHandler()
    planned = _planned_with_estimate("hello world", expected=64)
    result = await handler.handle(planned)
    assert isinstance(result, Success)
    finalized = result.value
    tv = cast("dict[str, object]", finalized.telemetry_data.get("token_validation", {}))
    assert set(tv.keys()) >= {
        "estimated_expected",
        "estimated_min",
        "estimated_max",
        "actual",
        "in_range",
    }
