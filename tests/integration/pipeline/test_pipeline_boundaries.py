"""Integration tests for the full pipeline boundary.

This test verifies the complete flow from InitialCommand to ResultEnvelope,
ensuring that all components (Planner, APIHandler, ResultBuilder) integrate
correctly without mocking internal interactions.
"""

from __future__ import annotations

import pytest

from pollux.config import resolve_config
from pollux.core.types import InitialCommand, Source
from pollux.executor import create_executor

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_full_pipeline_flow_end_to_end():
    """Verify data flows correctly through the entire pipeline.

    Uses 'google' provider to enable real planning/estimation logic, but relies on
    APIHandler's default `use_real_api=False` behavior to use the internal _MockAdapter
    for execution. This ensures metrics like token validation (which depend on logic
    consistency between plan and mock response) are generated.
    """
    # 1. Setup: Configure executor for Google/Gemini but without real API
    config = resolve_config(
        overrides={
            "provider": "google",
            "model": "gemini-2.0-flash",
            "api_key": "mock-key",
            "use_real_api": False,
        }
    )

    executor = create_executor(config)

    # 2. Input: Create a command with multiple sources and prompts
    cmd = InitialCommand(
        sources=(
            Source.from_text("Context document 1", identifier="doc1"),
            Source.from_text("Context document 2", identifier="doc2"),
        ),
        prompts=("Analyze these documents",),
        config=config,
    )

    # 3. Execution: Run the pipeline
    # No patching required; APIHandler defaults to _MockAdapter which echoes input.
    result_envelope = await executor.execute(cmd)

    # 4. Verification: Check the final output envelope
    assert result_envelope["status"] == "ok"

    # _MockAdapter echoes the input text
    answers = result_envelope["answers"]
    assert len(answers) == 1
    assert "echo: Analyze these documents" in answers[0]

    # Verify metrics framework integration
    metrics = result_envelope.get("metrics", {})
    assert isinstance(metrics, dict)

    # Duration metrics (ResultBuilder)
    assert "ResultBuilder" in metrics.get("durations", {})

    # Token validation metrics (ResultBuilder)
    # These should be present because 'google' provider enables proper estimation planning
    tv = metrics.get("token_validation", {})
    assert isinstance(tv, dict)
    for key in (
        "estimated_expected",
        "estimated_min",
        "estimated_max",
        "actual",
        "in_range",
    ):
        assert key in tv
    assert isinstance(tv["actual"], int)
    assert isinstance(tv["in_range"], bool)
