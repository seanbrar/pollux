"""Unit tests for result builder hint consumption and transform ordering."""

import pytest

from pollux.config import resolve_config
from pollux.core.execution_options import ExecutionOptions, ResultOption
from pollux.core.types import (
    APICall,
    ExecutionPlan,
    FinalizedCommand,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    Success,
    TextPart,
)
from pollux.pipeline.result_builder import ResultBuilder
from pollux.pipeline.results.transforms import (
    json_array_transform,
    simple_text_transform,
)

pytestmark = pytest.mark.unit


class TestResultBuilderHints:
    """Test result builder hint consumption and transform bias."""

    @pytest.fixture
    def basic_finalized_command(self):
        """Create a basic finalized command for testing."""
        config = resolve_config()
        initial = InitialCommand(
            sources=(),
            prompts=("test prompt",),
            config=config,
        )
        resolved = ResolvedCommand(initial=initial, resolved_sources=())
        call = APICall(
            model_name="gemini-2.0-flash", api_parts=(TextPart("test"),), api_config={}
        )
        plan = ExecutionPlan(calls=(call,))
        planned = PlannedCommand(resolved=resolved, execution_plan=plan)

        # Mock response that could match JSON array transform
        mock_response = '["answer1", "answer2"]'

        return FinalizedCommand(planned=planned, raw_api_response=mock_response)

    @pytest.fixture
    def builder_with_json_transforms(self):
        """Create result builder with json_array and simple_text transforms."""
        transforms = [
            json_array_transform(),
            simple_text_transform(),
        ]
        return ResultBuilder(transforms=tuple(transforms), enable_diagnostics=True)

    @pytest.mark.asyncio
    @pytest.mark.smoke
    async def test_no_hints_uses_default_transform_order(
        self, builder_with_json_transforms, basic_finalized_command
    ):
        """Without hints, should use default priority-based transform order."""
        result = await builder_with_json_transforms.handle(basic_finalized_command)

        assert isinstance(result, Success)
        envelope = result.value
        assert envelope["status"] == "ok"

        # JSON array transform has priority 90, simple_text has priority 50
        # So json_array should be tried first and succeed
        assert envelope["extraction_method"] == "json_array"
        # Should extract JSON array (may be normalized/padded by result builder)
        assert isinstance(envelope["answers"], list)
        assert len(envelope["answers"]) >= 1

    @pytest.mark.asyncio
    async def test_result_hint_biases_json_array_to_front(
        self, builder_with_json_transforms
    ):
        """ResultOption with prefer_json_array should bias json_array transform first."""
        config = resolve_config()
        initial = InitialCommand(
            sources=(),
            prompts=("test prompt",),
            config=config,
            options=ExecutionOptions(result=ResultOption(prefer_json_array=True)),
        )
        resolved = ResolvedCommand(initial=initial, resolved_sources=())
        call = APICall(
            model_name="gemini-2.0-flash", api_parts=(TextPart("test"),), api_config={}
        )
        plan = ExecutionPlan(calls=(call,))
        planned = PlannedCommand(resolved=resolved, execution_plan=plan)

        # Response that json_array transform can handle
        finalized = FinalizedCommand(
            planned=planned, raw_api_response='["biased1", "biased2"]'
        )

        result = await builder_with_json_transforms.handle(finalized)

        assert isinstance(result, Success)
        envelope = result.value
        assert envelope["status"] == "ok"
        assert envelope["extraction_method"] == "json_array"
        # Should have hint metadata in metrics
        assert (
            envelope.get("metrics", {}).get("hints", {}).get("prefer_json_array")
            is True
        )

    @pytest.mark.asyncio
    async def test_result_hint_fallback_still_works(self, builder_with_json_transforms):
        """ResultOption should not break Tier-2 fallback when JSON parsing fails."""
        config = resolve_config()
        initial = InitialCommand(
            sources=(),
            prompts=("test prompt",),
            config=config,
            options=ExecutionOptions(result=ResultOption(prefer_json_array=True)),
        )
        resolved = ResolvedCommand(initial=initial, resolved_sources=())
        call = APICall(
            model_name="gemini-2.0-flash", api_parts=(TextPart("test"),), api_config={}
        )
        plan = ExecutionPlan(calls=(call,))
        planned = PlannedCommand(resolved=resolved, execution_plan=plan)

        # Response that isn't valid JSON
        finalized = FinalizedCommand(
            planned=planned, raw_api_response="This is plain text, not JSON"
        )

        result = await builder_with_json_transforms.handle(finalized)

        assert isinstance(result, Success)
        envelope = result.value
        assert envelope["status"] == "ok"  # Should still succeed via fallback
        # Should fall back to simple_text or minimal projection
        assert envelope["extraction_method"] in ["simple_text", "minimal_text"]

    @pytest.mark.asyncio
    async def test_result_hint_false_preserves_normal_order(
        self,
        builder_with_json_transforms,
        basic_finalized_command,  # noqa: ARG002
    ):
        """ResultOption with prefer_json_array=False should not change ordering."""
        config = resolve_config()
        initial = InitialCommand(
            sources=(),
            prompts=("test prompt",),
            config=config,
            options=ExecutionOptions(result=ResultOption(prefer_json_array=False)),
        )
        resolved = ResolvedCommand(initial=initial, resolved_sources=())
        call = APICall(
            model_name="gemini-2.0-flash", api_parts=(TextPart("test"),), api_config={}
        )
        plan = ExecutionPlan(calls=(call,))
        planned = PlannedCommand(resolved=resolved, execution_plan=plan)

        finalized = FinalizedCommand(
            planned=planned, raw_api_response='["normal1", "normal2"]'
        )

        result = await builder_with_json_transforms.handle(finalized)

        assert isinstance(result, Success)
        envelope = result.value
        assert envelope["status"] == "ok"
        assert envelope["extraction_method"] == "json_array"
        # Should NOT have hint metadata for false preference
        assert (
            envelope.get("metrics", {}).get("hints", {}).get("prefer_json_array")
            is not True
        )

    @pytest.mark.asyncio
    async def test_transform_order_stable_without_preference(
        self, builder_with_json_transforms, basic_finalized_command
    ):
        """Without preference, default priority order applies and is stable."""
        result = await builder_with_json_transforms.handle(basic_finalized_command)
        assert isinstance(result, Success)
        env = result.value
        assert env["extraction_method"] == "json_array"

    @pytest.mark.asyncio
    async def test_prefer_json_option_bubbles_json_array(
        self, builder_with_json_transforms
    ):
        """ExecutionOptions.result should bias toward json_array when requested."""
        config = resolve_config()
        initial = InitialCommand(
            sources=(),
            prompts=("x",),
            config=config,
            options=ExecutionOptions(result=ResultOption(prefer_json_array=True)),
        )
        resolved = ResolvedCommand(initial=initial, resolved_sources=())
        call = APICall(
            model_name="gemini-2.0-flash", api_parts=(TextPart("test"),), api_config={}
        )
        plan = ExecutionPlan(calls=(call,))
        planned = PlannedCommand(resolved=resolved, execution_plan=plan)
        finalized = FinalizedCommand(planned=planned, raw_api_response='["a", "b"]')
        result = await builder_with_json_transforms.handle(finalized)
        assert isinstance(result, Success)
        assert result.value["extraction_method"] == "json_array"

    @pytest.mark.asyncio
    async def test_result_option_preference_records_metrics_flag(
        self, builder_with_json_transforms
    ):
        """When prefer_json is requested via options, metrics flag is recorded."""
        config = resolve_config()
        initial = InitialCommand(
            sources=(),
            prompts=("test prompt",),
            config=config,
            options=ExecutionOptions(result=ResultOption(prefer_json_array=True)),
        )
        resolved = ResolvedCommand(initial=initial, resolved_sources=())
        call = APICall(
            model_name="gemini-2.0-flash", api_parts=(TextPart("test"),), api_config={}
        )
        plan = ExecutionPlan(calls=(call,))
        planned = PlannedCommand(resolved=resolved, execution_plan=plan)

        finalized = FinalizedCommand(
            planned=planned, raw_api_response='["multi1", "multi2"]'
        )

        result = await builder_with_json_transforms.handle(finalized)

        assert isinstance(result, Success)
        envelope = result.value
        assert (
            envelope.get("metrics", {}).get("hints", {}).get("prefer_json_array")
            is True
        )

    @pytest.mark.asyncio
    async def test_result_hint_with_unknown_transform_name_safe(
        self,
        builder_with_json_transforms,  # noqa: ARG002
    ):
        """ResultOption should safely handle case where json_array transform doesn't exist."""
        # Create builder without json_array transform
        builder_no_json = ResultBuilder(transforms=(simple_text_transform(),))

        config = resolve_config()
        initial = InitialCommand(
            sources=(),
            prompts=("test prompt",),
            config=config,
            options=ExecutionOptions(result=ResultOption(prefer_json_array=True)),
        )
        resolved = ResolvedCommand(initial=initial, resolved_sources=())
        call = APICall(
            model_name="gemini-2.0-flash", api_parts=(TextPart("test"),), api_config={}
        )
        plan = ExecutionPlan(calls=(call,))
        planned = PlannedCommand(resolved=resolved, execution_plan=plan)

        finalized = FinalizedCommand(
            planned=planned, raw_api_response="plain text response"
        )

        result = await builder_no_json.handle(finalized)

        # Should still succeed - no json_array transform to bubble, so normal order
        assert isinstance(result, Success)
        envelope = result.value
        assert envelope["status"] == "ok"
