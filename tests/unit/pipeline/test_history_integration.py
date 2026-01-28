"""Integration tests for HistoryPart handling in the pipeline.

Ensures that HistoryPart is passed intact to adapters when non-empty,
and omitted when empty, maintaining architectural intent for conversational state.
"""

from __future__ import annotations

from typing import Any

import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    FinalizedCommand,
    HistoryPart,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    Success,
    TextPart,
    Turn,
)
from pollux.pipeline.api_handler import APIHandler

pytestmark = pytest.mark.unit


class CaptureAdapter:
    """Minimal adapter capturing the api_parts passed to generate() calls."""

    def __init__(self) -> None:
        self.parts_seen: list[tuple[str, tuple[Any, ...]]] = []

    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],
        api_config: dict[str, object],  # noqa: ARG002
    ) -> dict[str, Any]:
        self.parts_seen.append((model_name, api_parts))
        # Echo the last text-like part for determinism
        text = ""
        for p in reversed(api_parts):
            if hasattr(p, "text"):
                text = p.text
                break
        return {
            "model": model_name,
            "text": f"echo: {text}",
            "usage": {"total_token_count": 1},
        }


@pytest.mark.asyncio
async def test_history_part_reaches_adapter_intact() -> None:
    """Verify HistoryPart is passed intact to the adapter when non-empty."""
    cfg = resolve_config()
    initial = InitialCommand(sources=(), prompts=("A", "B"), config=cfg)
    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    # Build a vectorized plan with non-empty HistoryPart
    history = HistoryPart(turns=(Turn(question="q", answer="a"),))
    calls = (
        APICall(model_name="m", api_parts=(TextPart("A"),), api_config={}),
        APICall(model_name="m", api_parts=(TextPart("B"),), api_config={}),
    )
    plan = ExecutionPlan(
        calls=calls,
        shared_parts=(history,),
    )
    planned = PlannedCommand(resolved=resolved, execution_plan=plan)

    adapter = CaptureAdapter()
    handler = APIHandler(adapter=adapter)
    result = await handler.handle(planned)
    assert isinstance(result, Success)

    # Verify that each generate() received the HistoryPart among parts
    assert len(adapter.parts_seen) == 2
    for _, parts in adapter.parts_seen:
        assert any(hasattr(p, "turns") for p in parts), "HistoryPart missing"


@pytest.mark.asyncio
async def test_empty_history_is_omitted_in_single_call() -> None:
    """Ensure empty HistoryPart is omitted before reaching adapter."""
    cfg = resolve_config()
    initial = InitialCommand(sources=(), prompts=("Hi",), config=cfg)
    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    empty_history = HistoryPart(turns=())
    primary = APICall(model_name="m", api_parts=(TextPart("Hi"),), api_config={})
    plan = ExecutionPlan(calls=(primary,), shared_parts=(empty_history,))
    planned = PlannedCommand(resolved=resolved, execution_plan=plan)

    adapter = CaptureAdapter()
    handler = APIHandler(adapter=adapter)
    res = await handler.handle(planned)
    assert isinstance(res, Success)
    assert isinstance(res.value, FinalizedCommand)

    assert adapter.parts_seen, "Adapter should have been called"
    _, parts = adapter.parts_seen[0]
    # Ensure no structured history part reached the adapter
    assert not any(hasattr(p, "turns") for p in parts)
