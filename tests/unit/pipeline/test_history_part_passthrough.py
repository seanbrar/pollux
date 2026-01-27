"""Verify HistoryPart is passed intact to the adapter.

This test ensures the APIHandler no longer downgrades HistoryPart
to TextPart and that adapters receive the structured part.
"""

from __future__ import annotations

from typing import Any

import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    HistoryPart,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    TextPart,
)
from pollux.pipeline.api_handler import APIHandler

pytestmark = pytest.mark.unit


class CaptureAdapter:
    """Minimal adapter capturing the api_parts passed to generate() calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.caches: list[tuple[str, tuple[Any, ...]]] = []

    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],
        api_config: dict[str, object],  # noqa: ARG002
    ) -> dict[str, Any]:
        self.calls.append((model_name, api_parts))
        # Return a minimal raw response to satisfy handler
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
    cfg = resolve_config()
    initial = InitialCommand(sources=(), prompts=("A", "B"), config=cfg)
    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    # Build a vectorized plan with non-empty HistoryPart
    history = HistoryPart(
        turns=(
            # Minimal single turn to ensure the part is preserved
            # (empty histories are intentionally omitted by the handler)
            # Using placeholder values avoids tight coupling to provider formatting
            __import__("pollux.core.types", fromlist=["Turn"]).Turn(
                question="q", answer="a"
            ),
        )
    )
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
    assert hasattr(result, "value")

    # Verify that each generate() received the HistoryPart among parts
    assert len(adapter.calls) == 2
    for _, parts in adapter.calls:
        assert any(hasattr(p, "turns") for p in parts), "HistoryPart missing"
