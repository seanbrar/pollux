"""Tests for ResultBuilder handling of vectorized batch responses."""

from __future__ import annotations

import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    FinalizedCommand,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    Success,
)
from pollux.pipeline.result_builder import ResultBuilder

pytestmark = pytest.mark.unit


def _planned_with_prompts(n: int) -> PlannedCommand:
    cfg = resolve_config(overrides={"api_key": "test-key"})
    initial = InitialCommand(
        sources=(), prompts=tuple(f"P{i + 1}" for i in range(n)), config=cfg
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    from pollux.core.types import APICall, ExecutionPlan, TextPart

    primary = APICall(model_name="m", api_parts=(TextPart("joined"),), api_config={})
    plan = ExecutionPlan(calls=(primary,))
    return PlannedCommand(resolved=resolved, execution_plan=plan)


@pytest.mark.asyncio
async def test_result_builder_extracts_batch_answers() -> None:
    planned = _planned_with_prompts(2)
    raw = {"model": "m", "batch": ({"text": "echo: A"}, {"text": "echo: B"})}
    finalized = FinalizedCommand(planned=planned, raw_api_response=raw)

    builder = ResultBuilder()
    res = await builder.handle(finalized)
    assert isinstance(res, Success)
    out = res.value
    assert out.get("answers") == ["echo: A", "echo: B"]
    assert out.get("extraction_method") == "batch_response"
