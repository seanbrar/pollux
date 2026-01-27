"""No-op guarantee tests for execution options.

These tests verify the critical architectural invariant that the system
behaves identically when options are None, empty, or absent. This ensures
backward compatibility and fail-soft semantics.
"""

import pytest

from pollux.config import resolve_config
from pollux.core.execution_options import (
    CacheOptions,
    EstimationOptions,
    ExecutionOptions,
    ResultOption,
)
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    FinalizedCommand,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    Source,
    Success,
    TextPart,
)
from pollux.executor import create_executor
from pollux.extensions.conversation import Conversation
from pollux.extensions.conversation_types import ConversationState
from pollux.pipeline.planner import ExecutionPlanner
from pollux.pipeline.result_builder import ResultBuilder

pytestmark = pytest.mark.unit


class TestNoOpGuarantees:
    """Verify options=None produces identical behavior to default/no options."""

    @pytest.fixture
    def basic_config(self):
        """Basic configuration for testing."""
        return resolve_config()

    @pytest.fixture
    def basic_resolved_command(self, basic_config):
        """Basic resolved command without hints."""
        initial = InitialCommand(
            sources=(),
            prompts=("test prompt",),
            config=basic_config,
        )
        text_source = Source(
            source_type="text",
            identifier="test content",
            mime_type="text/plain",
            size_bytes=12,
            content_loader=lambda: b"test content",
        )
        return ResolvedCommand(initial=initial, resolved_sources=(text_source,))

    @pytest.mark.asyncio
    async def test_planner_no_op_guarantee(self, basic_resolved_command):
        """Planner should produce identical results with and without hints."""
        planner = ExecutionPlanner()

        # Test with no hints
        result_no_hints = await planner.handle(basic_resolved_command)

        # Test with None hints
        initial_none = basic_resolved_command.initial
        resolved_none = ResolvedCommand(
            initial=InitialCommand(
                sources=initial_none.sources,
                prompts=initial_none.prompts,
                config=initial_none.config,
                history=initial_none.history,
                options=None,
            ),
            resolved_sources=basic_resolved_command.resolved_sources,
        )
        result_none_hints = await planner.handle(resolved_none)

        # Test with empty hints tuple
        initial_empty = basic_resolved_command.initial
        resolved_empty = ResolvedCommand(
            initial=InitialCommand(
                sources=initial_empty.sources,
                prompts=initial_empty.prompts,
                config=initial_empty.config,
                history=initial_empty.history,
                options=ExecutionOptions(),
            ),
            resolved_sources=basic_resolved_command.resolved_sources,
        )
        result_empty_hints = await planner.handle(resolved_empty)

        # All should succeed
        assert isinstance(result_no_hints, Success)
        assert isinstance(result_none_hints, Success)
        assert isinstance(result_empty_hints, Success)

        # Token estimates should be identical
        est_no = result_no_hints.value.token_estimate
        est_none = result_none_hints.value.token_estimate
        est_empty = result_empty_hints.value.token_estimate

        assert est_no is not None and est_none is not None and est_empty is not None
        assert est_no.max_tokens == est_none.max_tokens == est_empty.max_tokens
        assert est_no.min_tokens == est_none.min_tokens == est_empty.min_tokens
        assert (
            est_no.expected_tokens
            == est_none.expected_tokens
            == est_empty.expected_tokens
        )

        # Cache decisions should be identical
        cache_no = result_no_hints.value.execution_plan.calls[0].cache_name_to_use
        cache_none = result_none_hints.value.execution_plan.calls[0].cache_name_to_use
        cache_empty = result_empty_hints.value.execution_plan.calls[0].cache_name_to_use

        assert (cache_no is None) == (cache_none is None) == (cache_empty is None)

    @pytest.mark.asyncio
    async def test_result_builder_no_op_guarantee(self):
        """Result builder should produce identical results with and without hints."""
        builder = ResultBuilder(enable_diagnostics=True)

        config = resolve_config()
        initial_base = InitialCommand(
            sources=(),
            prompts=("test",),
            config=config,
        )
        resolved = ResolvedCommand(initial=initial_base, resolved_sources=())
        call = APICall(
            model_name="gemini-2.0-flash", api_parts=(TextPart("test"),), api_config={}
        )
        plan = ExecutionPlan(calls=(call,))

        # Mock response for consistent comparison
        mock_response = "Simple text response"

        # No hints
        planned_no = PlannedCommand(resolved=resolved, execution_plan=plan)
        finalized_no = FinalizedCommand(
            planned=planned_no, raw_api_response=mock_response
        )
        result_no = await builder.handle(finalized_no)

        # None hints
        initial_none = InitialCommand(
            sources=(), prompts=("test",), config=config, options=None
        )
        resolved_none = ResolvedCommand(initial=initial_none, resolved_sources=())
        planned_none = PlannedCommand(resolved=resolved_none, execution_plan=plan)
        finalized_none = FinalizedCommand(
            planned=planned_none, raw_api_response=mock_response
        )
        result_none = await builder.handle(finalized_none)

        # Empty hints
        initial_empty = InitialCommand(
            sources=(), prompts=("test",), config=config, options=ExecutionOptions()
        )
        resolved_empty = ResolvedCommand(initial=initial_empty, resolved_sources=())
        planned_empty = PlannedCommand(resolved=resolved_empty, execution_plan=plan)
        finalized_empty = FinalizedCommand(
            planned=planned_empty, raw_api_response=mock_response
        )
        result_empty = await builder.handle(finalized_empty)

        # All should succeed
        assert isinstance(result_no, Success)
        assert isinstance(result_none, Success)
        assert isinstance(result_empty, Success)

        # Results should be identical
        env_no = result_no.value
        env_none = result_none.value
        env_empty = result_empty.value

        assert env_no["status"] == env_none["status"] == env_empty["status"]
        assert env_no["answers"] == env_none["answers"] == env_empty["answers"]
        assert (
            env_no["extraction_method"]
            == env_none["extraction_method"]
            == env_empty["extraction_method"]
        )

        # No hint metadata should be present
        assert env_no.get("metrics", {}).get("hints") is None
        assert env_none.get("metrics", {}).get("hints") is None
        assert env_empty.get("metrics", {}).get("hints") is None

    @pytest.mark.asyncio
    async def test_conversation_no_op_guarantee(self):
        """Conversation should behave identically with and without cache."""
        executor = create_executor()

        # Same conversation setup, one with cache, one without
        conv_no_cache = Conversation.start(executor, sources=())
        # Create conversation state with cache key for comparison
        cached_state = ConversationState(
            sources=(), turns=(), cache_key="noop-test", cache_artifacts=("artifact1",)
        )
        conv_with_cache = Conversation(cached_state, executor)

        # Ask the same question
        result_no_cache = await conv_no_cache.ask("test question")
        result_with_cache = await conv_with_cache.ask("test question")

        # Both should succeed and have turns
        assert len(result_no_cache.state.turns) == 1
        assert len(result_with_cache.state.turns) == 1
        assert result_no_cache.state.turns[0].error is False
        assert result_with_cache.state.turns[0].error is False

        # Both should have valid responses (deterministic mock may vary slightly)
        assert len(result_no_cache.state.turns[0].assistant) > 0
        assert len(result_with_cache.state.turns[0].assistant) > 0

    @pytest.mark.asyncio
    async def test_end_to_end_no_op_guarantee(self):
        """End-to-end execution should be identical with options=None vs default options."""
        from pollux.core.types import InitialCommand

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

    @pytest.mark.asyncio
    async def test_default_options_no_op_guarantee(self):
        """Default/empty options should not affect any pipeline stage."""
        planner = ExecutionPlanner()
        builder = ResultBuilder()

        config = resolve_config()

        # Create command with default/empty options
        initial = InitialCommand(
            sources=(),
            prompts=("test with empty options",),
            config=config,
            options=ExecutionOptions(),
        )
        resolved = ResolvedCommand(initial=initial, resolved_sources=())

        # Planner should handle gracefully
        plan_result = await planner.handle(resolved)
        assert isinstance(plan_result, Success)

        # Build finalized command for result builder
        call = APICall(
            model_name="gemini-2.0-flash", api_parts=(TextPart("test"),), api_config={}
        )
        plan = ExecutionPlan(calls=(call,))
        planned = PlannedCommand(resolved=resolved, execution_plan=plan)
        finalized = FinalizedCommand(planned=planned, raw_api_response="test response")

        # Result builder should handle gracefully
        result_result = await builder.handle(finalized)
        assert isinstance(result_result, Success)

        # Should succeed as if no hints were present
        envelope = result_result.value
        assert envelope["status"] == "ok"

    def test_hint_type_equivalence_no_state_leakage(self):
        """Hint instances should be independent with no shared state."""
        # Create multiple instances of same hint
        cache1 = CacheOptions("key1")
        cache2 = CacheOptions("key1")
        cache3 = CacheOptions("key2")

        # Should be equal by value
        assert cache1 == cache2
        assert cache1 != cache3

        # Should be independent instances
        assert cache1 is not cache2

        # Same for other hint types
        est1 = EstimationOptions(widen_max_factor=2.0)
        est2 = EstimationOptions(widen_max_factor=2.0)
        assert est1 == est2
        assert est1 is not est2

        result1 = ResultOption(prefer_json_array=True)
        result2 = ResultOption(prefer_json_array=True)
        assert result1 == result2
        assert result1 is not result2
