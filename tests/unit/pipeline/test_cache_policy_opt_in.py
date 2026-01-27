"""Cache policy opt-in tests when config disables caching.

Verifies that providing a CachePolicyHint via ExecutionOptions allows the
CacheStage to create/apply a cache even when `enable_caching` is False.
"""

from __future__ import annotations

from typing import Any

import pytest

from pollux.config import resolve_config
from pollux.core.execution_options import CachePolicyHint, ExecutionOptions
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    TextPart,
    TokenEstimate,
)
from pollux.pipeline.adapters.base import CachingCapability, GenerationAdapter
from pollux.pipeline.cache_stage import CacheStage
from pollux.pipeline.registries import CacheRegistry


class _DummyCachingAdapter(GenerationAdapter, CachingCapability):
    """Minimal adapter implementing caching + generation protocols for tests."""

    # GenerationAdapter requirement (never used by this test, but satisfies typing)
    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],
        api_config: dict[str, object],
    ) -> dict[str, Any]:  # pragma: no cover - not exercised here
        # Touch args to satisfy linters without changing the signature
        _ = (model_name, api_parts, api_config)
        return {
            "status": "ok",
            "answers": ["stub"],
            "extraction_method": "stub",
            "confidence": 1.0,
        }

    # CachingCapability requirement used by CacheStage
    async def create_cache(
        self,
        *,
        model_name: str,
        content_parts: tuple[Any, ...],
        system_instruction: str | None,
        ttl_seconds: int | None,
    ) -> str:
        _ = (content_parts, system_instruction, ttl_seconds)
        # Deterministic test cache name
        return f"cachedContents/test-{model_name}-ok"


def _adapter_factory(_: str) -> _DummyCachingAdapter:
    return _DummyCachingAdapter()


@pytest.mark.asyncio
async def test_cache_policy_enables_when_config_disabled() -> None:
    """Policy hint should opt-in caching even if config.enable_caching=False."""
    cfg = resolve_config(
        overrides={
            "use_real_api": True,  # ensure CacheStage attempts adapter selection
            "api_key": "dummy-key",
            "enable_caching": False,  # explicitly disabled in config
            "model": "gemini-2.0-flash",
        }
    )

    # Build InitialCommand with options carrying a cache policy hint
    initial = InitialCommand(
        sources=(),
        prompts=("p",),
        config=cfg,
        options=ExecutionOptions(cache_policy=CachePolicyHint()),
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    # Non-empty shared parts so CacheStage has payload to cache
    call = APICall(
        model_name=str(cfg.model or "gemini-2.0-flash"),
        api_parts=(TextPart(text="user"),),
        api_config={},
        cache_name_to_use=None,
    )
    plan = ExecutionPlan(
        calls=(call,),
        shared_parts=(TextPart(text="shared"),),
    )

    # Provide a token estimate above the explicit minimum floor (4096)
    est = TokenEstimate(
        min_tokens=0, expected_tokens=5000, max_tokens=5000, confidence=0.95
    )
    planned = PlannedCommand(resolved=resolved, execution_plan=plan, token_estimate=est)

    stage = CacheStage(
        registries={"cache": CacheRegistry()},
        adapter_factory=_adapter_factory,
    )

    result = await stage.handle(planned)
    from pollux.core.types import Success

    assert isinstance(result, Success), (
        f"unexpected failure: {getattr(result, 'error', None)}"
    )
    updated = result.value
    # Cache should be applied to the call despite config.enable_caching=False
    assert updated.execution_plan.calls[0].cache_name_to_use is not None
