"""Tests for APIHandler attaching raw preview under telemetry metrics."""

from __future__ import annotations

from typing import Any, cast

import pytest

from pollux.config import resolve_config
from pollux.core.types import InitialCommand, ResolvedCommand, Success
from pollux.pipeline.api_handler import APIHandler
from pollux.pipeline.planner import ExecutionPlanner

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_api_handler_attaches_raw_preview_when_enabled_constructor() -> None:
    cfg = resolve_config(overrides={"api_key": "test-key"})
    initial = InitialCommand(sources=(), prompts=("A", "B"), config=cfg)
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    planned_res = await ExecutionPlanner().handle(resolved)
    assert isinstance(planned_res, Success)
    planned = planned_res.value

    handler = APIHandler(include_raw_preview=True)
    final_res = await handler.handle(planned)
    assert isinstance(final_res, Success)
    finalized = final_res.value

    metrics = cast("dict[str, Any]", finalized.telemetry_data.get("metrics", {}))
    rp = metrics.get("raw_preview")
    assert isinstance(rp, dict)
    assert rp.get("model") == planned.execution_plan.calls[0].model_name
    batch = rp.get("batch")
    assert isinstance(batch, tuple) and len(batch) == 2
    # Each per-call preview should be a small dict with at least text or repr
    assert all(isinstance(x, dict) for x in batch)
    assert ("text" in batch[0]) or ("repr" in batch[0])


@pytest.mark.asyncio
async def test_api_handler_attaches_raw_preview_via_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("POLLUX_TELEMETRY_RAW_PREVIEW", "1")
    cfg = resolve_config(overrides={"api_key": "test-key"})
    initial = InitialCommand(sources=(), prompts=("Q1",), config=cfg)
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    planned_res = await ExecutionPlanner().handle(resolved)
    assert isinstance(planned_res, Success)
    planned = planned_res.value

    handler = APIHandler()  # inherit from env flag
    final_res = await handler.handle(planned)
    assert isinstance(final_res, Success)
    finalized = final_res.value
    metrics = cast("dict[str, Any]", finalized.telemetry_data.get("metrics", {}))
    rp = metrics.get("raw_preview")
    assert isinstance(rp, dict)
    assert isinstance(rp.get("batch"), tuple) and len(rp["batch"]) == 1


@pytest.mark.asyncio
async def test_api_handler_does_not_attach_raw_preview_when_disabled_env(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("POLLUX_TELEMETRY_RAW_PREVIEW", raising=False)
    cfg = resolve_config(overrides={"api_key": "test-key"})
    initial = InitialCommand(sources=(), prompts=("Only",), config=cfg)
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    planned_res = await ExecutionPlanner().handle(resolved)
    assert isinstance(planned_res, Success)
    planned = planned_res.value

    handler = APIHandler()  # default, env disabled
    final_res = await handler.handle(planned)
    assert isinstance(final_res, Success)
    finalized = final_res.value
    metrics = cast("dict[str, Any]", finalized.telemetry_data.get("metrics", {}))
    rp = metrics.get("raw_preview")
    assert rp is None
