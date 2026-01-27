"""ExecutionOptions.cache_override_name behavior tests.

Ensures the CacheStage applies the override name to the plan without requiring
an adapter or registry interactions, and that it coexists with normal paths.
"""

from __future__ import annotations

import pytest

from pollux.config import resolve_config
from pollux.core.execution_options import ExecutionOptions
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    TextPart,
)
from pollux.pipeline.cache_stage import CacheStage


@pytest.mark.asyncio
async def test_cache_override_applies_without_adapter() -> None:
    """Override should apply cache name even when no real adapter is selected."""
    cfg = resolve_config(overrides={"use_real_api": False})
    initial = InitialCommand(
        sources=(),
        prompts=("p",),
        config=cfg,
        options=ExecutionOptions(cache_override_name="cachedContents/manual-override"),
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    call = APICall(
        model_name=str(cfg.model or "gemini-2.0-flash"),
        api_parts=(TextPart(text="t"),),
        api_config={},
    )
    plan = ExecutionPlan(calls=(call,), shared_parts=(TextPart(text="shared"),))
    planned = PlannedCommand(resolved=resolved, execution_plan=plan)

    stage = CacheStage()
    result = await stage.handle(planned)
    from pollux.core.types import Success

    assert isinstance(result, Success)
    updated = result.value
    assert (
        updated.execution_plan.calls[0].cache_name_to_use
        == "cachedContents/manual-override"
    )
