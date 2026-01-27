"""Tests for vectorized planning and execution (A1/A2)."""

from __future__ import annotations

from typing import Any

import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    HistoryPart,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    Success,
    Turn,
)
from pollux.pipeline.api_handler import APIHandler
from pollux.pipeline.planner import ExecutionPlanner

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_planner_emits_calls_and_shared_parts_with_history() -> None:
    cfg = resolve_config(overrides={"api_key": "test-key"})
    history = (
        Turn(question="Hello", answer="Hi"),
        Turn(question="How are you?", answer="Great"),
    )
    initial = InitialCommand(
        sources=(),
        prompts=("P1", "P2"),
        config=cfg,
        history=history,
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    planner = ExecutionPlanner()
    result = await planner.handle(resolved)
    assert isinstance(result, Success)
    planned = result.value
    plan = planned.execution_plan

    # Vectorized path: N calls, shared parts include history
    assert plan.calls and len(plan.calls) == 2
    assert any(isinstance(p, HistoryPart) for p in plan.shared_parts)
    # Per-call estimates present and aggregate estimate exists
    assert planned.per_call_estimates and len(planned.per_call_estimates) == 2
    assert planned.token_estimate is not None


class _CachingEchoAdapter:
    """Simple test adapter that supports caching and echoes last text part."""

    def __init__(self) -> None:
        self.created: list[tuple[str, int | None]] = []

    async def create_cache(
        self,
        *,
        model_name: str,
        content_parts: tuple[Any, ...],  # noqa: ARG002
        system_instruction: str | None,  # noqa: ARG002
        ttl_seconds: int | None,
    ) -> str:
        self.created.append((model_name, ttl_seconds))
        return f"cachedContents/test-{model_name}-1"

    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],
        api_config: dict[str, object],  # noqa: ARG002
    ) -> dict[str, Any]:
        text = ""
        for part in reversed(api_parts):
            if hasattr(part, "text"):
                text = str(part.text)
                break
        return {
            "model": model_name,
            "text": f"echo: {text}",
            "usage": {"total_token_count": max(len(text) // 4 + 10, 0)},
        }


@pytest.mark.asyncio
async def test_api_handler_executes_vectorized_and_aggregates_usage() -> None:
    cfg = resolve_config(overrides={"api_key": "test-key"})
    initial = InitialCommand(sources=(), prompts=("A", "B"), config=cfg)
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    planner = ExecutionPlanner()
    planned_res = await planner.handle(resolved)
    assert isinstance(planned_res, Success)
    planned = planned_res.value

    handler = APIHandler()  # default mock adapter
    final_res = await handler.handle(planned)
    assert isinstance(final_res, Success)
    finalized = final_res.value

    raw = finalized.raw_api_response
    assert isinstance(raw, dict) and "batch" in raw
    batch = raw["batch"]
    assert isinstance(batch, tuple) and len(batch) == 2
    # Echo per-prompt texts
    assert batch[0].get("text", "").endswith("A")
    assert batch[1].get("text", "").endswith("B")
    # Telemetry contains per_prompt and aggregated usage
    metrics = finalized.telemetry_data.get("metrics", {})
    usage = finalized.telemetry_data.get("usage", {})
    assert isinstance(metrics, dict) and isinstance(usage, dict)
    per_prompt = metrics.get("per_prompt")
    assert isinstance(per_prompt, tuple) and len(per_prompt) == 2
    total = usage.get("total_token_count")
    assert isinstance(total, int) and total == sum(
        int(u.get("total_token_count", 0)) for u in per_prompt
    )


@pytest.mark.asyncio
async def test_shared_cache_created_once_for_vectorized() -> None:
    # Attach history to trigger shared cache planning
    cfg = resolve_config(overrides={"api_key": "test-key"})
    history = (Turn(question="hi", answer="there"),)
    initial = InitialCommand(
        sources=(), prompts=("A", "B"), config=cfg, history=history
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    planned = await ExecutionPlanner().handle(resolved)
    assert isinstance(planned, Success)
    planned_cmd: PlannedCommand = planned.value

    # Use adapter with CachingCapability
    adapter = _CachingEchoAdapter()
    handler = APIHandler(adapter=adapter)
    final = await handler.handle(planned_cmd)
    assert isinstance(final, Success)
    # create_cache should be called at most once
    assert len(adapter.created) <= 1


@pytest.mark.asyncio
async def test_batch_response_transform_extracts_multiple_answers() -> None:
    """Test that the batch response transform correctly extracts multiple answers from batch structure."""
    from pollux.pipeline.results.transforms import batch_response_transform

    transform = batch_response_transform()

    # Mock batch response structure (what API handler creates)
    batch_response = {
        "model": "gemini-2.0-flash",
        "batch": (
            {"text": "echo: First question answer"},
            {"text": "echo: Second question answer"},
            {"text": "echo: Third question answer"},
        ),
    }

    # Test matcher
    assert transform.matcher(batch_response) is True

    # Test extractor
    result = transform.extractor(batch_response, {})
    assert result["answers"] == [
        "echo: First question answer",
        "echo: Second question answer",
        "echo: Third question answer",
    ]
    assert result["confidence"] == 0.85
