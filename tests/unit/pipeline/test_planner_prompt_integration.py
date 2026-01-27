"""Integration tests for prompt assembly in planner."""

from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from pollux.config import resolve_config
from pollux.core.types import (
    InitialCommand,
    ResolvedCommand,
    Source,
    Success,
    TextPart,
)
from pollux.pipeline.planner import ExecutionPlanner

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_planner_with_system_instruction():
    """Test planner integration with system instruction."""
    config = resolve_config(
        overrides={
            "api_key": "test-key",
            "prompts.system": "You are a helpful assistant.",
        }
    )

    planner = ExecutionPlanner()
    initial = InitialCommand(
        sources=(),
        prompts=("What is AI?",),
        config=config,
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    result = await planner.handle(resolved)

    assert isinstance(result, Success)
    planned = result.value
    primary = planned.execution_plan.calls[0]

    # Check that system instruction is in API config
    assert (
        primary.api_config.get("system_instruction") == "You are a helpful assistant."
    )

    # Check that user prompts are preserved
    assert len(primary.api_parts) == 1
    first_part = primary.api_parts[0]
    assert isinstance(first_part, TextPart)
    assert first_part.text == "What is AI?"


@pytest.mark.asyncio
async def test_planner_with_prefix_suffix():
    """Test planner integration with prefix and suffix."""
    config = resolve_config(
        overrides={
            "api_key": "test-key",
            "prompts.prefix": "Q: ",
            "prompts.suffix": " Please be concise.",
        }
    )

    planner = ExecutionPlanner()
    initial = InitialCommand(
        sources=(),
        prompts=("What is ML?", "How does it work?"),
        config=config,
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    result = await planner.handle(resolved)

    assert isinstance(result, Success)
    planned = result.value
    plan = planned.execution_plan
    # Vectorized path: ensure two calls with individually transformed prompts
    assert plan.calls and len(plan.calls) == 2
    c0, c1 = plan.calls
    p0 = c0.api_parts[0]
    p1 = c1.api_parts[0]
    assert isinstance(p0, TextPart) and isinstance(p1, TextPart)
    assert p0.text == "Q: What is ML? Please be concise."
    assert p1.text == "Q: How does it work? Please be concise."


@pytest.mark.asyncio
async def test_planner_with_sources_block():
    """Test planner integration with source-aware guidance."""
    config = resolve_config(
        overrides={
            "api_key": "test-key",
            "prompts.system": "You are helpful.",
            "prompts.sources_policy": "append_or_replace",
            "prompts.sources_block": "Use the attached sources if relevant.",
        }
    )

    planner = ExecutionPlanner()
    initial = InitialCommand(
        sources=(Source.from_text("doc.txt"),),
        prompts=("Summarize the content",),
        config=config,
    )

    # Create a realistic mock source
    mock_source = Source(
        source_type="file",
        identifier="doc.txt",
        mime_type="text/plain",
        size_bytes=100,
        content_loader=lambda: b"Sample document content",
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=(mock_source,))

    result = await planner.handle(resolved)

    assert isinstance(result, Success)
    planned = result.value
    primary = planned.execution_plan.calls[0]

    # Check that sources block is appended to system instruction
    expected_system = "You are helpful.\n\nUse the attached sources if relevant."
    assert primary.api_config.get("system_instruction") == expected_system


@pytest.mark.asyncio
async def test_planner_with_system_file():
    """Test planner integration with system instruction from file."""
    with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("System instruction from file.")
        system_file_path = f.name

    try:
        config = resolve_config(
            overrides={
                "api_key": "test-key",
                "prompts.system_file": system_file_path,
            }
        )

        planner = ExecutionPlanner()
        initial = InitialCommand(
            sources=(),
            prompts=("Test prompt",),
            config=config,
        )
        resolved = ResolvedCommand(initial=initial, resolved_sources=())

        result = await planner.handle(resolved)

        assert isinstance(result, Success)
        planned = result.value
        primary = planned.execution_plan.calls[0]

        # Check that system instruction is loaded from file
        assert (
            primary.api_config.get("system_instruction")
            == "System instruction from file."
        )

    finally:
        Path(system_file_path).unlink()


@pytest.mark.asyncio
async def test_planner_cache_key_includes_system_instruction():
    """Test that cache keys include system instruction for proper cache separation."""
    config = resolve_config(
        overrides={
            "api_key": "test-key",
            "enable_caching": True,
            "prompts.system": "System A",
        }
    )

    planner = ExecutionPlanner()
    initial = InitialCommand(
        sources=(),
        prompts=(
            "Test prompt with lots of tokens " * 1000,
        ),  # Large prompt to trigger caching
        config=config,
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    result1 = await planner.handle(resolved)
    assert isinstance(result1, Success)

    # Change system instruction
    config2 = resolve_config(
        overrides={
            "api_key": "test-key",
            "enable_caching": True,
            "prompts.system": "System B",
        }
    )
    initial2 = InitialCommand(
        sources=(),
        prompts=("Test prompt with lots of tokens " * 1000,),
        config=config2,
    )
    resolved2 = ResolvedCommand(initial=initial2, resolved_sources=())

    result2 = await planner.handle(resolved2)
    assert isinstance(result2, Success)

    # Cache keys should be different due to different system instructions
    plan1 = result1.value.execution_plan
    plan2 = result2.value.execution_plan

    cache_name1 = plan1.calls[0].cache_name_to_use
    cache_name2 = plan2.calls[0].cache_name_to_use

    # If caching is enabled, cache names should be different for different system instructions
    if cache_name1 is not None and cache_name2 is not None:
        assert cache_name1 != cache_name2, (
            f"Cache names should differ with different system instructions: {cache_name1} == {cache_name2}"
        )


@pytest.mark.asyncio
async def test_planner_no_system_instruction():
    """Test planner works normally when no system instruction is configured."""
    config = resolve_config(overrides={"api_key": "test-key"})

    planner = ExecutionPlanner()
    initial = InitialCommand(
        sources=(),
        prompts=("Simple prompt",),
        config=config,
    )
    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    result = await planner.handle(resolved)

    assert isinstance(result, Success)
    planned = result.value
    primary = planned.execution_plan.calls[0]

    # No system instruction should be present
    assert primary.api_config.get("system_instruction") is None
    assert len(primary.api_config) == 0  # Should be empty


@pytest.mark.asyncio
async def test_planner_user_file_with_empty_initial_prompts():
    """Test planner with user_file when initial prompts are empty."""
    with NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Prompt from user file.")
        user_file_path = f.name

    try:
        config = resolve_config(
            overrides={
                "api_key": "test-key",
                "prompts.user_file": user_file_path,
            }
        )

        planner = ExecutionPlanner()
        initial = InitialCommand(
            sources=(),
            prompts=(),  # Empty prompts
            config=config,
        )
        resolved = ResolvedCommand(initial=initial, resolved_sources=())

        result = await planner.handle(resolved)

        assert isinstance(result, Success)
        planned = result.value
        primary = planned.execution_plan.calls[0]

        # Check that prompt is loaded from user file
        first_part = primary.api_parts[0]
        assert isinstance(first_part, TextPart)
        assert first_part.text == "Prompt from user file."

    finally:
        Path(user_file_path).unlink()
