"""No-op guarantee tests for execution options.

These tests verify the critical architectural invariant that the system
behaves identically when options are None, empty, or absent. This ensures
backward compatibility and fail-soft semantics.
"""

import pytest

from pollux.config import resolve_config
from pollux.core.execution_options import (
    ExecutionOptions,
)
from pollux.core.types import (
    InitialCommand,
)
from pollux.executor import create_executor

pytestmark = pytest.mark.contract


class TestExecutionOptionsContract:
    """Verify options=None produces identical behavior to default/no options."""

    @pytest.mark.asyncio
    async def test_end_to_end_no_op_guarantee(self):
        """End-to-end execution should be identical with options=None vs default options."""

        executor = create_executor()

        # Command with explicit options=None
        cmd_none = InitialCommand(
            sources=(), prompts=("e2e test",), config=resolve_config(), options=None
        )

        # Command with empty hints tuple
        cmd_empty = InitialCommand(
            sources=(),
            prompts=("e2e test",),
            config=resolve_config(),
            options=ExecutionOptions(),
        )

        # Execute both through full pipeline
        result_none = await executor.execute(cmd_none)
        result_empty = await executor.execute(cmd_empty)

        # Results should be functionally identical
        assert result_none["status"] == result_empty["status"]
        assert result_none["extraction_method"] == result_empty["extraction_method"]
        # Both should have valid answers
        assert isinstance(result_none["answers"], list)
        assert isinstance(result_empty["answers"], list)
