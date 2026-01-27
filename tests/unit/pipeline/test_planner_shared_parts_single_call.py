"""Planner symmetry tests: single-call shared parts shape.

Ensures that in the single-call path, file placeholders live in shared_parts
and are not included in the primary_call.api_parts. Prompt text remains in
the primary call parts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pollux.config import resolve_config
from pollux.core.types import InitialCommand, ResolvedCommand
from pollux.pipeline.planner import ExecutionPlanner

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_single_call_shared_parts_carry_files_only_prompt_in_api_parts(
    tmp_path: Path,
) -> None:
    # Arrange: one file source, single prompt
    file_path = tmp_path / "doc.pdf"
    file_path.write_bytes(b"%PDF-1.4 test")

    cfg = resolve_config()
    from pollux.core.types import Source

    source = Source.from_file(file_path)
    initial = InitialCommand(sources=(source,), prompts=("Hello?",), config=cfg)
    from pollux.pipeline.source_handler import SourceHandler

    # Resolve sources via the SourceHandler to materialize Source objects
    resolved_result = await SourceHandler().handle(initial)
    assert hasattr(resolved_result, "value")
    resolved: ResolvedCommand = resolved_result.value

    # Act: plan execution
    planner = ExecutionPlanner()
    planned_result = await planner.handle(resolved)
    assert hasattr(planned_result, "value")
    plan = planned_result.value.execution_plan

    # Assert: shared_parts contains a FilePlaceholder; primary.api_parts contain only TextPart
    from pollux.core.types import FilePlaceholder, TextPart

    assert any(isinstance(p, FilePlaceholder) for p in plan.shared_parts)
    assert all(isinstance(p, TextPart) for p in plan.calls[0].api_parts)
