import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    Failure,
    FinalizedCommand,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    Source,
    Success,
    TextPart,
)
from pollux.pipeline.adapters.base import GenerationAdapter
from pollux.pipeline.api_handler import APIHandler


def make_planned(prompts: tuple[str, ...]) -> PlannedCommand:
    initial = InitialCommand(
        sources=(Source.from_text("s"),),
        prompts=prompts,
        config=resolve_config(overrides={"api_key": "k"}),
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    call = APICall(
        model_name="gemini-2.0-flash",
        api_parts=(TextPart(text="\n\n".join(prompts)),),
        api_config={},
    )
    plan = ExecutionPlan(calls=(call,))
    return PlannedCommand(resolved=resolved, execution_plan=plan)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_api_handler_uses_planned_parts():
    handler = APIHandler()
    planned = make_planned(("hello",))
    result = await handler.handle(planned)
    assert isinstance(result, Success)
    finalized: FinalizedCommand = result.value
    raw = finalized.raw_api_response
    assert isinstance(raw, dict)
    # The response is a batch with individual responses
    batch = raw.get("batch", [])
    assert len(batch) == 1
    response = batch[0]
    assert "echo: hello" in response.get("text", "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_api_handler_fails_on_empty_parts():
    handler = APIHandler()
    initial = InitialCommand(
        sources=(Source.from_text("s"),),
        prompts=("p",),
        config=resolve_config(overrides={"api_key": "k"}),
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    empty_call = APICall(model_name="gemini-2.0-flash", api_parts=(), api_config={})
    plan = ExecutionPlan(calls=(empty_call,))
    planned = PlannedCommand(resolved=resolved, execution_plan=plan)

    result = await handler.handle(planned)
    assert isinstance(result, Failure)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_factory_requires_api_key_and_fails_explicitly():
    # Factory provided but no api_key in config should trigger explicit Failure
    def _factory(
        _api_key: str,
    ) -> GenerationAdapter:  # pragma: no cover - not called in this test
        raise AssertionError("Factory should not be invoked without api_key")

    handler = APIHandler(adapter_factory=_factory)
    initial = InitialCommand(
        sources=(Source.from_text("s"),),
        prompts=("p",),
        config=resolve_config(overrides={}),
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())
    call = APICall(
        model_name="gemini-2.0-flash", api_parts=(TextPart("p"),), api_config={}
    )
    plan = ExecutionPlan(calls=(call,))
    planned = PlannedCommand(resolved=resolved, execution_plan=plan)

    result = await handler.handle(planned)
    assert isinstance(result, Failure)
    assert "api_key" in str(result.error).lower()
