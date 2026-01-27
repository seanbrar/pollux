from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from pollux.config import resolve_config
from pollux.core.api_parts import TextPart
from pollux.core.api_plan import APICall, ExecutionPlan
from pollux.core.commands import InitialCommand, PlannedCommand, ResolvedCommand
from pollux.core.types import Success
from pollux.pipeline.adapters.base import CachingCapability, GenerationAdapter
from pollux.pipeline.cache_stage import CacheStage
from pollux.pipeline.registries import CacheRegistry


@dataclass
class _FakeCachingAdapter(GenerationAdapter, CachingCapability):
    calls: int = 0

    async def create_cache(
        self,
        *,
        model_name: str,
        content_parts: tuple[Any, ...],
        system_instruction: str | None,
        ttl_seconds: int | None,
    ) -> str:
        _ = system_instruction, ttl_seconds
        self.calls += 1
        await asyncio.sleep(0.05)
        return f"cachedContents/test-{model_name}-{len(content_parts)}"

    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],
        api_config: dict[str, object],
    ) -> dict[str, Any]:  # pragma: no cover - not used
        _ = api_parts, api_config
        return {"model": model_name}


@pytest.mark.asyncio
async def test_cache_creation_is_single_flight() -> None:
    cfg = resolve_config(
        overrides={"use_real_api": True, "api_key": "x", "enable_caching": True}
    )

    initial = InitialCommand.strict(sources=(), prompts=("p",), config=cfg)
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    # Use shared_parts to trigger cache payload shaping
    plan = ExecutionPlan(
        calls=(
            APICall(model_name=cfg.model, api_parts=(TextPart("u"),), api_config={}),
        ),
        shared_parts=(TextPart("shared"),),
    )
    command = PlannedCommand(resolved=resolved, execution_plan=plan)

    reg = CacheRegistry()
    adapter = _FakeCachingAdapter()
    stage = CacheStage(registries={"cache": reg}, adapter_factory=lambda _: adapter)

    # Run two concurrent handle() calls; only one cache should be created
    r1, r2 = await asyncio.gather(stage.handle(command), stage.handle(command))
    assert isinstance(r1, Success) and isinstance(r2, Success)
    c1 = r1.value.execution_plan.calls[0].cache_name_to_use
    c2 = r2.value.execution_plan.calls[0].cache_name_to_use
    assert isinstance(c1, str) and c1 == c2
    assert adapter.calls == 1
