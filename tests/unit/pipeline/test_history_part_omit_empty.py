"""Ensure empty HistoryPart is omitted before reaching adapter."""

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
)
from pollux.pipeline.api_handler import APIHandler

pytestmark = pytest.mark.unit


class _CapturePartsAdapter:
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
        return {"model": model_name, "text": "ok", "usage": {"total_token_count": 1}}


@pytest.mark.asyncio
async def test_empty_history_is_omitted_in_single_call() -> None:
    cfg = resolve_config()
    initial = InitialCommand(sources=(), prompts=("Hi",), config=cfg)
    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    empty_history = HistoryPart(turns=())
    primary = APICall(model_name="m", api_parts=(TextPart("Hi"),), api_config={})
    plan = ExecutionPlan(calls=(primary,), shared_parts=(empty_history,))
    planned = PlannedCommand(resolved=resolved, execution_plan=plan)

    adapter = _CapturePartsAdapter()
    handler = APIHandler(adapter=adapter)
    res = await handler.handle(planned)
    assert isinstance(res, Success)
    assert isinstance(res.value, FinalizedCommand)

    assert adapter.parts_seen, "Adapter should have been called"
    _, parts = adapter.parts_seen[0]
    # Ensure no structured history part reached the adapter
    assert not any(hasattr(p, "turns") for p in parts)
