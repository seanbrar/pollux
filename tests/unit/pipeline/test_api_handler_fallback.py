from typing import Any, cast

import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    Failure,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    Source,
    Success,
    TextPart,
)
from pollux.pipeline.api_handler import APIHandler
from pollux.telemetry import (
    _EnabledTelemetryContext,  # test-only: explicit enabled context
    _SimpleReporter,
)


def _make_planned(
    primary_text: str, fallback_text: str | None = None
) -> PlannedCommand:
    initial = InitialCommand(
        sources=(Source.from_text("s"),),
        prompts=(primary_text,),
        config=resolve_config(overrides={"api_key": "test-key"}),
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    primary = APICall(
        model_name="gemini-2.0-flash",
        api_parts=(TextPart(text=primary_text),),
        api_config={},
    )
    fallback = (
        APICall(
            model_name="gemini-2.0-flash",
            api_parts=(TextPart(text=fallback_text or "fallback"),),
            api_config={},
        )
        if fallback_text is not None
        else None
    )
    plan = ExecutionPlan(calls=(primary,), fallback_call=fallback)
    return PlannedCommand(resolved=resolved, execution_plan=plan)


class _FakeAdapter:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.calls = 0

    async def generate(
        self,
        *,
        model_name: str,
        api_parts: tuple[Any, ...],  # noqa: ARG002
        api_config: dict[str, object],  # noqa: ARG002
    ) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("primary boom")
        return {"text": "ok", "model": model_name, "usage": {"total_token_count": 10}}


@pytest.mark.asyncio
async def test_fallback_runs_once_and_succeeds():
    # Use explicit factory to avoid env coupling and private telemetry enablement
    def factory(_api_key: str | None) -> Any:
        return _FakeAdapter()

    reporter = _SimpleReporter()
    handler = APIHandler(
        telemetry=_EnabledTelemetryContext(reporter),
        adapter_factory=factory,
    )
    planned = _make_planned("primary", fallback_text="fallback")

    result = await handler.handle(planned)
    assert isinstance(result, Success)
    raw = result.value.raw_api_response
    assert isinstance(raw, dict)
    # Vectorized response shape: inspect first batch item
    b0 = raw.get("batch", ({},))[0]
    assert isinstance(b0, dict) and b0.get("text") == "ok"

    # Telemetry scopes should contain api.execute, api.generate, api.fallback
    timing_keys = set(reporter.timings.keys())
    assert any(k == "api.execute" for k in timing_keys)
    assert any(k.endswith("api.generate") for k in timing_keys)
    assert any(k.endswith("api.fallback") for k in timing_keys)

    # Assert execution.used_fallback toggles and primary_error exists
    # Per-call metadata is recorded under metrics.per_call_meta
    metrics = cast("dict[str, object]", result.value.telemetry_data.get("metrics", {}))
    per_call = cast("tuple[dict[str, object], ...]", metrics.get("per_call_meta", ()))
    assert len(per_call) >= 1
    assert per_call[0].get("used_fallback") is True
    assert "primary_error" in per_call[0]


@pytest.mark.asyncio
async def test_fallback_absent_propagates_error():
    class _AlwaysFail:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        async def generate(
            self,
            *,
            model_name: str,  # noqa: ARG002
            api_parts: tuple[Any, ...],  # noqa: ARG002
            api_config: dict[str, object],  # noqa: ARG002
        ) -> dict[str, Any]:
            raise RuntimeError("always fail")

    def factory(_api_key: str | None) -> Any:
        return _AlwaysFail()

    handler = APIHandler(adapter_factory=factory)
    planned = _make_planned("primary", fallback_text=None)

    result = await handler.handle(planned)
    assert isinstance(result, Failure)
    assert "Provider call failed" in str(result.error)


@pytest.mark.asyncio
async def test_api_handler_fallback_to_adapter_factory():
    # Factory will produce a fake adapter that returns a deterministic response
    class _FakeAdapter:
        async def generate(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {"text": "echo: fallback"}

    def _factory(_api_key: str) -> Any:
        return _FakeAdapter()

    handler = APIHandler(adapter_factory=_factory)
    initial = InitialCommand(
        sources=(Source.from_text("s"),),
        prompts=("p",),
        config=resolve_config(overrides={"api_key": "test-key"}),
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    call = APICall(
        model_name="gemini-2.0-flash", api_parts=(TextPart("p"),), api_config={}
    )
    plan = ExecutionPlan(calls=(call,))
    planned = PlannedCommand(resolved=resolved, execution_plan=plan)

    result = await handler.handle(planned)
    assert isinstance(result, Success)
    finalized = result.value
    b0 = finalized.raw_api_response.get("batch", ({},))[0]
    assert "echo: fallback" in b0.get("text", "")
