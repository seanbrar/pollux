"""Unit tests for the main ResultBuilder Two-Tier Transform Chain.

Tests the complete Result Builder implementation, verifying the orchestration
of transforms, fallback behavior, schema validation, and adherence to the
architecture rubric's guarantee of 100% extraction success rate.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pollux.core.types import (
    APICall,
    ExecutionPlan,
    FinalizedCommand,
    InitialCommand,
    PlannedCommand,
    ResolvedCommand,
    Success,
)
from pollux.pipeline.result_builder import ResultBuilder
from pollux.pipeline.results.extraction import (
    ExtractionContext,
    TransformSpec,
)

# Ensure async tests run under pytest without relying on external configuration
pytestmark = pytest.mark.asyncio


def create_mock_finalized_command(
    raw_response: Any,
    prompts: tuple[str, ...] = ("Test prompt",),
    telemetry_data: dict[str, Any] | None = None,
) -> FinalizedCommand:
    """Create a mock FinalizedCommand for testing."""
    if telemetry_data is None:
        telemetry_data = {
            "durations": {"api_call": 123.45},
            "token_validation": {"estimated": 100, "actual": 95},
        }

    initial = InitialCommand(
        sources=(), prompts=prompts, config=MagicMock(), history=()
    )

    resolved = ResolvedCommand(initial=initial, resolved_sources=())

    execution_plan = ExecutionPlan(
        calls=(APICall(model_name="test-model", api_parts=(), api_config={}),)
    )

    planned = PlannedCommand(resolved=resolved, execution_plan=execution_plan)

    return FinalizedCommand(
        planned=planned, raw_api_response=raw_response, telemetry_data=telemetry_data
    )


class TestResultBuilderBasicBehavior:
    """Test basic Result Builder behavior and guarantees."""

    async def test_always_returns_success(self):
        """ResultBuilder should never fail - always return Success."""
        builder = ResultBuilder()

        # Test various inputs that might cause failures
        problematic_inputs = [
            None,
            "",
            {},
            [],
            {"malformed": "data"},
            Exception("test error"),
            object(),
        ]

        for input_data in problematic_inputs:
            command = create_mock_finalized_command(input_data)
            result = await builder.handle(command)

            # Should always be Success, never Failure
            assert isinstance(result, Success)
            assert result.value["status"] == "ok"
            assert "answers" in result.value
            assert isinstance(result.value["answers"], list)

    async def test_json_array_extraction(self):
        """ResultBuilder should use JSON array transform for JSON input."""
        builder = ResultBuilder()

        json_response = '["answer1", "answer2", "answer3"]'
        command = create_mock_finalized_command(
            json_response, prompts=("Q1", "Q2", "Q3")
        )

        result = await builder.handle(command)

        assert isinstance(result, Success)
        assert result.value["status"] == "ok"
        assert result.value["answers"] == ["answer1", "answer2", "answer3"]
        assert result.value["extraction_method"] == "json_array"
        assert result.value["confidence"] == 0.95

    async def test_provider_response_extraction(self):
        """ResultBuilder should handle provider SDK response structures."""
        builder = ResultBuilder()

        provider_response = {
            "candidates": [{"content": {"parts": [{"text": "Provider response text"}]}}]
        }
        command = create_mock_finalized_command(provider_response)

        result = await builder.handle(command)

        assert isinstance(result, Success)

        assert result.value["status"] == "ok"
        assert result.value["answers"] == ["Provider response text"]
        assert result.value["extraction_method"] == "provider_normalized"

    async def test_fallback_to_minimal_projection(self):
        """ResultBuilder should fall back to MinimalProjection when transforms fail."""
        # Disable Tier 1 transforms to force Tier 2 fallback
        builder = ResultBuilder(transforms=())

        # Text input; with transforms disabled this forces fallback
        simple_text = "This is a simple response that doesn't match structured formats"
        command = create_mock_finalized_command(simple_text)

        result = await builder.handle(command)

        assert isinstance(result, Success)

        assert result.value["status"] == "ok"
        assert result.value["answers"] == [simple_text]
        assert result.value["extraction_method"].startswith("minimal_")

    async def test_answer_count_padding(self):
        """ResultBuilder should pad answers to match expected count."""
        builder = ResultBuilder()

        # Single answer but expecting multiple
        json_response = '["single_answer"]'
        command = create_mock_finalized_command(
            json_response,
            prompts=("Q1", "Q2", "Q3"),  # Expecting 3 answers
        )

        result = await builder.handle(command)

        assert isinstance(result, Success)

        assert len(result.value["answers"]) == 3
        assert result.value["answers"] == ["single_answer", "", ""]

    async def test_answer_count_truncation(self):
        """ResultBuilder should truncate excess answers."""
        builder = ResultBuilder()

        # Multiple answers but expecting fewer
        json_response = '["answer1", "answer2", "answer3", "answer4"]'
        command = create_mock_finalized_command(
            json_response,
            prompts=("Q1", "Q2"),  # Expecting only 2 answers
        )

        result = await builder.handle(command)

        assert isinstance(result, Success)

        assert len(result.value["answers"]) == 2
        assert result.value["answers"] == ["answer1", "answer2"]

    async def test_telemetry_data_integration(self):
        """ResultBuilder should integrate telemetry data from command."""
        builder = ResultBuilder()

        telemetry_data = {
            "durations": {"api_call": 150.0, "planning": 25.0},
            "token_validation": {"estimated": 200, "actual": 180},
        }

        command = create_mock_finalized_command(
            "Simple response", telemetry_data=telemetry_data
        )

        result = await builder.handle(command)

        assert isinstance(result, Success)

        assert "metrics" in result.value
        assert result.value["metrics"]["durations"]["api_call"] == 150.0
        assert result.value["metrics"]["token_validation"]["estimated"] == 200

    async def test_malformed_telemetry_graceful_degradation(self):
        """ResultBuilder should handle malformed telemetry gracefully."""
        builder = ResultBuilder()

        # Malformed telemetry data
        command = create_mock_finalized_command(
            "Simple response",
            telemetry_data="not a dict",  # type: ignore[arg-type]
        )

        result = await builder.handle(command)

        # Should still succeed with best-effort metrics
        assert isinstance(result, Success)

        assert result.value["status"] == "ok"
        assert "metrics" in result.value
        assert isinstance(result.value["metrics"]["durations"], dict)
        assert isinstance(result.value["metrics"]["token_validation"], dict)


class TestResultBuilderTransformOrdering:
    """Test transform priority ordering and selection."""

    async def test_transform_priority_ordering(self):
        """Transforms should be tried in priority order."""
        # Create transforms with different priorities
        low_priority = TransformSpec(
            name="low_priority",
            matcher=lambda _x: True,  # Always matches
            extractor=lambda _x, _c: {"answers": ["low"], "confidence": 0.1},
            priority=10,
        )

        high_priority = TransformSpec(
            name="high_priority",
            matcher=lambda _x: True,  # Always matches
            extractor=lambda _x, _c: {"answers": ["high"], "confidence": 0.9},
            priority=90,
        )

        builder = ResultBuilder(transforms=(low_priority, high_priority))
        command = create_mock_finalized_command("test input")

        result = await builder.handle(command)

        # Should use high priority transform
        assert isinstance(result, Success)

        assert result.value["extraction_method"] == "high_priority"
        assert result.value["answers"] == ["high"]

    async def test_transform_name_tiebreaker(self):
        """Equal priority transforms should be ordered by name."""
        transform_zebra = TransformSpec(
            name="zebra_transform",
            matcher=lambda _x: True,
            extractor=lambda _x, _c: {"answers": ["zebra"], "confidence": 0.5},
            priority=50,
        )

        transform_alpha = TransformSpec(
            name="alpha_transform",
            matcher=lambda _x: True,
            extractor=lambda _x, _c: {"answers": ["alpha"], "confidence": 0.5},
            priority=50,  # Same priority
        )

        builder = ResultBuilder(transforms=(transform_zebra, transform_alpha))
        command = create_mock_finalized_command("test input")

        result = await builder.handle(command)

        # Should use alpha (alphabetically first)
        assert isinstance(result, Success)

        assert result.value["extraction_method"] == "alpha_transform"
        assert result.value["answers"] == ["alpha"]

    async def test_transform_matching_logic(self):
        """Only matching transforms should be tried."""
        never_matches = TransformSpec(
            name="never_matches",
            matcher=lambda _x: False,  # Never matches
            extractor=lambda _x, _c: {"answers": ["never"], "confidence": 0.9},
            priority=100,  # Highest priority
        )

        always_matches = TransformSpec(
            name="always_matches",
            matcher=lambda _x: True,  # Always matches
            extractor=lambda _x, _c: {"answers": ["always"], "confidence": 0.5},
            priority=50,  # Lower priority
        )

        builder = ResultBuilder(transforms=(never_matches, always_matches))
        command = create_mock_finalized_command("test input")

        result = await builder.handle(command)

        # Should use the matching transform despite lower priority
        assert isinstance(result, Success)

        assert result.value["extraction_method"] == "always_matches"
        assert result.value["answers"] == ["always"]

    async def test_transform_exception_handling(self):
        """Transform exceptions should be handled gracefully."""
        failing_transform = TransformSpec(
            name="failing_transform",
            matcher=lambda _x: True,
            extractor=lambda _x, _c: (_ for _ in ()).throw(
                RuntimeError("Transform failed")
            ),
            priority=90,
        )

        working_transform = TransformSpec(
            name="working_transform",
            matcher=lambda _x: True,
            extractor=lambda _x, _c: {"answers": ["working"], "confidence": 0.7},
            priority=50,
        )

        builder = ResultBuilder(transforms=(failing_transform, working_transform))
        command = create_mock_finalized_command("test input")

        result = await builder.handle(command)

        # Should use working transform after first one fails
        assert isinstance(result, Success)

        assert result.value["extraction_method"] == "working_transform"
        assert result.value["answers"] == ["working"]


class TestResultBuilderDiagnostics:
    """Test diagnostic collection and reporting."""

    async def test_diagnostics_disabled_by_default(self):
        """Diagnostics should be disabled by default."""
        builder = ResultBuilder()
        command = create_mock_finalized_command("test input")

        result = await builder.handle(command)

        # Should not have diagnostics field
        assert isinstance(result, Success)

        assert "diagnostics" not in result.value

    async def test_diagnostics_enabled_collection(self):
        """Diagnostics should be collected when enabled."""
        builder = ResultBuilder(enable_diagnostics=True)
        command = create_mock_finalized_command('["answer1", "answer2"]')

        result = await builder.handle(command)

        # Should have diagnostics
        assert isinstance(result, Success)

        assert "diagnostics" in result.value
        diagnostics = result.value["diagnostics"]

        assert "attempted_transforms" in diagnostics
        assert "successful_transform" in diagnostics
        assert "extraction_duration_ms" in diagnostics
        assert isinstance(diagnostics["extraction_duration_ms"], float)

    async def test_transform_error_logging(self):
        """Transform errors should be logged in diagnostics."""
        failing_transform = TransformSpec(
            name="failing_transform",
            matcher=lambda _x: True,
            extractor=lambda _x, _c: (_ for _ in ()).throw(ValueError("Test error")),
            priority=90,
        )

        builder = ResultBuilder(
            transforms=(failing_transform,), enable_diagnostics=True
        )
        command = create_mock_finalized_command("test input")

        result = await builder.handle(command)

        assert isinstance(result, Success)

        diagnostics = result.value["diagnostics"]
        assert "transform_errors" in diagnostics
        assert "failing_transform" in diagnostics["transform_errors"]
        assert "Test error" in diagnostics["transform_errors"]["failing_transform"]

    async def test_attempted_transforms_tracking(self):
        """Attempted transforms should be tracked in diagnostics."""
        transform1 = TransformSpec(
            name="transform1",
            matcher=lambda _x: False,  # Won't match
            extractor=lambda _x, _c: {"answers": ["t1"], "confidence": 0.5},
            priority=90,
        )

        transform2 = TransformSpec(
            name="transform2",
            matcher=lambda _x: True,  # Will match
            extractor=lambda _x, _c: {"answers": ["t2"], "confidence": 0.5},
            priority=80,
        )

        builder = ResultBuilder(
            transforms=(transform1, transform2), enable_diagnostics=True
        )
        command = create_mock_finalized_command("test input")

        result = await builder.handle(command)

        assert isinstance(result, Success)

        diagnostics = result.value["diagnostics"]
        assert diagnostics["attempted_transforms"] == ["transform1", "transform2"]
        assert diagnostics["successful_transform"] == "transform2"


class TestResultBuilderValidation:
    """Test schema and contract validation (record-only)."""

    async def test_contract_validation_violations(self):
        """Contract violations should be recorded but not fail extraction."""
        builder = ResultBuilder()

        # Single answer but expecting multiple
        command = create_mock_finalized_command(
            "Single answer",
            prompts=("Q1", "Q2", "Q3"),  # Expecting 3 answers
        )

        result = await builder.handle(command)

        assert isinstance(result, Success)

        # Should still succeed
        assert result.value["status"] == "ok"

        # Should have validation warnings
        assert "validation_warnings" in result.value
        warnings = result.value["validation_warnings"]
        assert any("Expected 3 answers, got 1" in warning for warning in warnings)

    async def test_schema_validation_with_diagnostics(self):
        """Schema validation violations should be included in diagnostics."""

        # Mock Pydantic schema that always fails
        class MockSchema:
            @staticmethod
            def model_validate(_data):
                raise ValueError("Schema validation failed")

        builder = ResultBuilder(enable_diagnostics=True)

        # Create context with schema
        original_build_context = builder._build_extraction_context

        def mock_build_context(_self, command):
            ctx = original_build_context(command)
            # Replace with version that has schema
            return ExtractionContext(
                expected_count=ctx.expected_count,
                prompts=ctx.prompts,
                config=ctx.config,
                schema=MockSchema(),
            )

        # Temporarily patch the instance method to avoid assigning directly
        # to a method attribute (static analysis-friendly).
        with patch.object(
            builder.__class__, "_build_extraction_context", mock_build_context
        ):
            command = create_mock_finalized_command("test input")
            result = await builder.handle(command)

        assert isinstance(result, Success)

        # Should still succeed
        assert result.value["status"] == "ok"

        # Should have violations in diagnostics
        diagnostics = result.value["diagnostics"]
        assert "contract_violations" in diagnostics
        violations = diagnostics["contract_violations"]
        assert any("Schema validation failed" in v["message"] for v in violations)


class TestResultBuilderResponseTruncation:
    """Test response size limits and truncation."""

    async def test_oversized_response_truncation(self):
        """Oversized responses should be truncated."""
        builder = ResultBuilder(max_text_size=100)  # Small limit for testing

        # Create oversized response
        large_response = "x" * 200  # Exceeds limit
        command = create_mock_finalized_command(large_response)

        result = await builder.handle(command)

        assert isinstance(result, Success)

        # Should still succeed
        assert result.value["status"] == "ok"

        # Response should be truncated
        answer = result.value["answers"][0]
        assert len(answer) <= 100 + len("... [TRUNCATED]")
        assert answer.endswith("... [TRUNCATED]")

    async def test_truncation_flag_in_diagnostics(self):
        """Truncation should be flagged in diagnostics."""
        builder = ResultBuilder(max_text_size=50, enable_diagnostics=True)

        large_response = "x" * 100
        command = create_mock_finalized_command(large_response)

        result = await builder.handle(command)

        assert isinstance(result, Success)

        diagnostics = result.value["diagnostics"]
        assert "truncated_input" in diagnostics["flags"]

    async def test_dict_response_truncation(self):
        """Dict responses should have text fields truncated."""
        builder = ResultBuilder(max_text_size=50)

        large_dict = {
            "text": "x" * 100,  # Exceeds limit
            "other": "normal field",
        }
        command = create_mock_finalized_command(large_dict)

        result = await builder.handle(command)

        assert isinstance(result, Success)

        # Should still succeed and truncate the text field
        assert result.value["status"] == "ok"


class TestResultBuilderStructuredData:
    """Test structured data preservation in results."""

    async def test_structured_data_preservation(self):
        """Structured data should be preserved in result envelope."""
        builder = ResultBuilder()

        json_response = '["answer1", "answer2"]'
        command = create_mock_finalized_command(json_response)

        result = await builder.handle(command)

        assert isinstance(result, Success)

        # Should preserve original structured data
        assert "structured_data" in result.value
        assert result.value["structured_data"] == ["answer1", "answer2"]

    async def test_no_structured_data_omission(self):
        """Result envelope should omit structured_data when not available."""
        builder = ResultBuilder()

        text_response = "Simple text response"
        command = create_mock_finalized_command(text_response)

        result = await builder.handle(command)

        # For plain text (MinimalProjection) `structured_data` may be absent or
        # None; ensure we don't set it unexpectedly.
        assert isinstance(result, Success)
        result_value = result.value
        assert result_value.get("structured_data") in (None, [])


class TestResultBuilderAdditional:
    """Additional high-value tests for envelope, config, diagnostics, and usage."""

    async def test_transform_receives_config(self):
        """Ensure transforms receive context config (plumbing works)."""

        def matcher(_x: Any) -> bool:
            return True

        def extractor(_x: Any, cfg: dict[str, Any]) -> dict[str, Any]:
            return {"answers": [cfg.get("prefix", "") + "value"], "confidence": 0.9}

        spec = TransformSpec(
            name="cfg_transform", matcher=matcher, extractor=extractor, priority=100
        )

        builder = ResultBuilder(transforms=(spec,))
        original_build = builder._build_extraction_context

        def patched_build(_self, command):
            ctx = original_build(command)
            return ExtractionContext(
                expected_count=ctx.expected_count,
                prompts=ctx.prompts,
                config={"prefix": "x-"},
                schema=ctx.schema,
            )

        with patch.object(
            builder.__class__, "_build_extraction_context", patched_build
        ):
            command = create_mock_finalized_command("ignored")
            result = await builder.handle(command)

        assert isinstance(result, Success)
        assert result.value["answers"] == ["x-value"]

    async def test_diagnostics_flags_are_list(self):
        """Diagnostics flags set is normalized to list in result."""
        builder = ResultBuilder(enable_diagnostics=True, max_text_size=1)
        command = create_mock_finalized_command("xx")  # triggers truncation
        result = await builder.handle(command)
        assert isinstance(result, Success)
        flags = result.value["diagnostics"]["flags"]
        assert isinstance(flags, list)
        assert "truncated_input" in flags

    async def test_mismatch_recorded_pre_normalization_in_diagnostics(self):
        # Use JSON transform so pre-normalization answers length < expected
        builder = ResultBuilder(enable_diagnostics=True)
        command = create_mock_finalized_command(
            '["only one"]', prompts=("Q1", "Q2", "Q3")
        )
        result = await builder.handle(command)
        assert isinstance(result, Success)
        d = result.value["diagnostics"]
        assert d["expected_answer_count"] == 3
        assert d["pre_pad_count"] == 1
        assert any(
            "Expected 3 answers, got 1" in v["message"]
            for v in d["contract_violations"]
        )

    async def test_dict_text_field_truncated(self):
        builder = ResultBuilder(max_text_size=5)
        large = {"text": "abcdefghi", "other": "ok"}
        command = create_mock_finalized_command(large)
        result = await builder.handle(command)
        assert isinstance(result, Success)
        assert result.value["answers"][0].endswith("... [TRUNCATED]")

    async def test_usage_metrics_integration_optional(self):
        builder = ResultBuilder()
        telemetry = {
            "durations": {"api_call": 10.0},
            "token_validation": {"estimated": 10, "actual": 9},
            "usage": {"input_tokens": 123, "output_tokens": 45},
        }
        command = create_mock_finalized_command("simple", telemetry_data=telemetry)
        result = await builder.handle(command)
        assert isinstance(result, Success)
        assert result.value["usage"]["input_tokens"] == 123
        assert result.value["usage"]["output_tokens"] == 45

    async def test_envelope_core_fields_and_types(self):
        builder = ResultBuilder()
        for raw in (
            "text",
            {"candidates": [{"content": {"parts": [{"text": "t"}]}}]},
            "",
        ):
            command = create_mock_finalized_command(raw)
            result = await builder.handle(command)
            assert isinstance(result, Success)
            val = result.value
            assert isinstance(val["status"], str)
            assert isinstance(val["answers"], list)
            assert isinstance(val["extraction_method"], str)
            assert isinstance(val["confidence"], float)

    async def test_fallback_method_whitelist(self):
        builder = ResultBuilder(transforms=())  # force fallback
        command = create_mock_finalized_command("a\nb")
        result = await builder.handle(command)
        assert isinstance(result, Success)
        method = result.value["extraction_method"]
        assert method in {
            "minimal_json",
            "minimal_numbered",
            "minimal_newlines",
            "minimal_text",
        }

    async def test_answers_are_strings_after_extraction(self):
        builder = ResultBuilder()
        json_response = '["string", 123, true, null]'
        command = create_mock_finalized_command(
            json_response, prompts=("Q1", "Q2", "Q3", "Q4")
        )
        result = await builder.handle(command)
        assert isinstance(result, Success)
        assert result.value["answers"] == ["string", "123", "True", ""]
