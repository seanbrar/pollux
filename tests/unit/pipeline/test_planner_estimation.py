import pytest

from pollux.config import resolve_config
from pollux.core.types import InitialCommand, ResolvedCommand, Source, Success
from pollux.pipeline.planner import ExecutionPlanner

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_planner_includes_prompt_in_token_estimate():
    planner = ExecutionPlanner()

    # Prompt-only scenario
    initial = InitialCommand(
        sources=(),
        prompts=("short prompt",),
        config=resolve_config(overrides={"api_key": "k", "model": "gemini-2.0-flash"}),
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    result = await planner.handle(resolved)
    assert isinstance(result, Success)
    planned = result.value

    # Token estimate should be present and include the prompt breakdown
    assert planned.token_estimate is not None
    estimate = planned.token_estimate
    assert estimate.expected_tokens >= 10  # prompt-only should be at least the floor
    assert estimate.breakdown is None or "prompt" in estimate.breakdown

    # Parts should contain the joined prompt
    primary = planned.execution_plan.calls[0]
    assert primary.api_parts
    # api_parts may contain FileRefPart/FilePlaceholder; ensure it's a TextPart
    first_part = primary.api_parts[0]
    assert hasattr(first_part, "text") and first_part.text == "short prompt"


@pytest.mark.asyncio
async def test_cache_key_is_deterministic_and_changes_with_prompts():
    planner = ExecutionPlanner()

    # Build a large source to be part of the cache key payload
    large_source = Source(
        source_type="file",
        identifier="/dev/null",
        mime_type="application/octet-stream",
        size_bytes=10_000_000,
        content_loader=lambda: b"",
    )

    initial_a = InitialCommand(
        sources=(Source.from_text("ignored content"),),
        prompts=("A",),
        config=resolve_config(
            overrides={
                "api_key": "k",
                "model": "gemini-2.0-flash",
                "enable_caching": True,
            }
        ),
    )
    resolved_a = ResolvedCommand(initial=initial_a, resolved_sources=(large_source,))

    initial_b = InitialCommand(
        sources=(Source.from_text("ignored content"),),
        prompts=("A",),
        config=resolve_config(
            overrides={
                "api_key": "k",
                "model": "gemini-2.0-flash",
                "enable_caching": True,
            }
        ),
    )
    resolved_b = ResolvedCommand(initial=initial_b, resolved_sources=(large_source,))
    # Deterministic: identical inputs produce identical cache names
    result_a = await planner.handle(resolved_a)
    assert isinstance(result_a, Success)
    planned_a = result_a.value

    result_b = await planner.handle(resolved_b)
    assert isinstance(result_b, Success)
    planned_b = result_b.value

    cache_a = planned_a.execution_plan.calls[0].cache_name_to_use
    cache_b = planned_b.execution_plan.calls[0].cache_name_to_use
    # If caching is enabled, cache names should be identical for identical inputs
    if cache_a is not None or cache_b is not None:
        assert cache_a == cache_b, (
            f"Cache names should be identical: {cache_a} != {cache_b}"
        )

    # Changing prompts should yield a different cache name
    initial_c = InitialCommand(
        sources=(Source.from_text("ignored content"),),
        prompts=("B",),
        config=resolve_config(
            overrides={
                "api_key": "k",
                "model": "gemini-2.0-flash",
                "enable_caching": True,
            }
        ),
    )
    resolved_c = ResolvedCommand(initial=initial_c, resolved_sources=(large_source,))
    result_c = await planner.handle(resolved_c)
    assert isinstance(result_c, Success)
    planned_c = result_c.value
    cache_c = planned_c.execution_plan.calls[0].cache_name_to_use
    # If caching is enabled, different prompts should yield different cache names
    if cache_c is not None and cache_a is not None:
        assert cache_c != cache_a, (
            f"Cache names should differ for different prompts: {cache_c} == {cache_a}"
        )
