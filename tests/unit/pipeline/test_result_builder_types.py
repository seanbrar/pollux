"""Unit tests for Result Builder core types and data structures.

Tests the fundamental data types that enable the Two-Tier Transform Chain,
focusing on validation, immutability, and contract adherence according
to the architecture rubric principles.
"""

from typing import Any, cast

import pytest

from pollux.pipeline.results.extraction import (
    ExtractionContext,
    ExtractionContract,
    ExtractionDiagnostics,
    ExtractionResult,
    TransformSpec,
    Violation,
)

pytestmark = pytest.mark.unit


class TestTransformSpec:
    """Test TransformSpec validation and behavior."""

    def test_valid_transform_spec(self):
        """Valid TransformSpec should initialize without errors."""

        def matcher(_raw):
            return True

        def extractor(_raw, _ctx):
            return {"answers": ["test"]}

        spec = TransformSpec(
            name="test_transform", matcher=matcher, extractor=extractor, priority=50
        )

        assert spec.name == "test_transform"
        assert spec.matcher is matcher
        assert spec.extractor is extractor
        assert spec.priority == 50

    def test_transform_spec_immutable(self):
        """TransformSpec should be immutable (frozen dataclass)."""

        def matcher(_raw):
            return True

        def extractor(_raw, _ctx):
            return {"answers": ["test"]}

        spec = TransformSpec(
            name="test_transform", matcher=matcher, extractor=extractor
        )

        with pytest.raises(AttributeError):
            spec.name = "changed"  # type: ignore

        with pytest.raises(AttributeError):
            spec.priority = 100  # type: ignore

    def test_empty_name_validation(self):
        """Empty or non-string name should raise ValueError."""

        def dummy_func(_x):
            return True

        with pytest.raises(ValueError, match="Transform name must be non-empty string"):
            TransformSpec(
                name="",
                matcher=dummy_func,
                extractor=cast("Any", dummy_func),
            )

        with pytest.raises(ValueError, match="Transform name must be non-empty string"):
            TransformSpec(
                name=cast("Any", None),
                matcher=dummy_func,
                extractor=cast("Any", dummy_func),
            )

    def test_non_callable_matcher_validation(self):
        """Non-callable matcher should raise ValueError."""

        def dummy_func(_x):
            return True

        with pytest.raises(ValueError, match="matcher must be callable"):
            TransformSpec(
                name="test",
                matcher=cast("Any", "not callable"),
                extractor=cast("Any", dummy_func),
            )

    def test_non_callable_extractor_validation(self):
        """Non-callable extractor should raise ValueError."""

        def dummy_func(_x):
            return True

        with pytest.raises(ValueError, match="extractor must be callable"):
            TransformSpec(
                name="test",
                matcher=dummy_func,
                extractor=cast("Any", "not callable"),
            )

    def test_default_priority(self):
        """TransformSpec should have default priority of 0."""

        def matcher(_raw):
            return True

        def extractor(_raw, _ctx):
            return {}

        spec = TransformSpec(name="test", matcher=matcher, extractor=extractor)
        assert spec.priority == 0


class TestExtractionContext:
    """Test ExtractionContext validation and behavior."""

    def test_valid_extraction_context(self):
        """Valid ExtractionContext should initialize with defaults."""
        ctx = ExtractionContext()

        assert ctx.expected_count == 1
        assert ctx.schema is None
        assert ctx.config == {}
        assert ctx.prompts == ()

    def test_custom_extraction_context(self):
        """ExtractionContext should accept custom values."""
        ctx = ExtractionContext(
            expected_count=5,
            schema="mock_schema",
            config={"test": "value"},
            prompts=("prompt1", "prompt2"),
        )

        assert ctx.expected_count == 5
        assert ctx.schema == "mock_schema"
        assert ctx.config == {"test": "value"}
        assert ctx.prompts == ("prompt1", "prompt2")

    def test_extraction_context_immutable(self):
        """ExtractionContext should be immutable."""
        ctx = ExtractionContext(expected_count=3)

        with pytest.raises(AttributeError):
            ctx.expected_count = 5  # type: ignore

    def test_invalid_expected_count(self):
        """expected_count < 1 should raise ValueError."""
        with pytest.raises(ValueError, match="expected_count must be >= 1"):
            ExtractionContext(expected_count=0)

        with pytest.raises(ValueError, match="expected_count must be >= 1"):
            ExtractionContext(expected_count=-1)


class TestViolation:
    """Test Violation data structure."""

    def test_valid_violation(self):
        """Valid Violation should initialize correctly."""
        violation = Violation("Test message", "error")

        assert violation.message == "Test message"
        assert violation.severity == "error"

    def test_default_severity(self):
        """Violation should default to 'warning' severity."""
        violation = Violation("Test message")

        assert violation.severity == "warning"

    def test_violation_immutable(self):
        """Violation should be immutable."""
        violation = Violation("Test message")

        with pytest.raises(AttributeError):
            violation.message = "Changed"  # type: ignore

    def test_empty_message_validation(self):
        """Empty message should raise ValueError."""
        with pytest.raises(ValueError, match="Violation message cannot be empty"):
            Violation("")


class TestExtractionContract:
    """Test ExtractionContract validation and behavior."""

    def test_default_extraction_contract(self):
        """Default ExtractionContract should have sensible defaults."""
        contract = ExtractionContract()

        assert contract.answer_count is None
        assert contract.min_answer_length == 0
        assert contract.max_answer_length == 100_000
        assert contract.required_fields == frozenset()

    def test_custom_extraction_contract(self):
        """Custom ExtractionContract should accept parameters."""
        contract = ExtractionContract(
            answer_count=5,
            min_answer_length=10,
            max_answer_length=1000,
            required_fields=frozenset(["field1", "field2"]),
        )

        assert contract.answer_count == 5
        assert contract.min_answer_length == 10
        assert contract.max_answer_length == 1000
        assert contract.required_fields == frozenset(["field1", "field2"])

    def test_contract_validation_constraints(self):
        """Contract validation should check parameter constraints."""
        # min_answer_length must be >= 0
        with pytest.raises(ValueError, match="min_answer_length must be >= 0"):
            ExtractionContract(min_answer_length=-1)

        # max_answer_length must be >= min_answer_length
        with pytest.raises(
            ValueError, match="max_answer_length.*must be >= min_answer_length"
        ):
            ExtractionContract(min_answer_length=100, max_answer_length=50)

    def test_validate_answer_count(self):
        """Contract should validate answer count when specified."""
        contract = ExtractionContract(answer_count=2)

        # Correct count - no violations
        result = {"answers": ["answer1", "answer2"]}
        violations = contract.validate(result)
        assert len(violations) == 0

        # Wrong count - should create violation
        result = {"answers": ["answer1"]}
        violations = contract.validate(result)
        assert len(violations) == 1
        assert "Expected 2 answers, got 1" in violations[0].message

    def test_validate_answer_lengths(self):
        """Contract should validate answer lengths."""
        contract = ExtractionContract(min_answer_length=5, max_answer_length=10)

        # Valid lengths - no violations
        result = {"answers": ["12345", "1234567890"]}
        violations = contract.validate(result)
        assert len(violations) == 0

        # Too short
        result = {"answers": ["1234"]}
        violations = contract.validate(result)
        assert len(violations) == 1
        assert "minimum 5" in violations[0].message

        # Too long
        result = {"answers": ["12345678901"]}
        violations = contract.validate(result)
        assert len(violations) == 1
        assert "maximum 10" in violations[0].message

    def test_validate_required_fields(self):
        """Contract should validate required fields."""
        contract = ExtractionContract(required_fields=frozenset(["field1", "field2"]))

        # All fields present - no violations
        result = {"field1": "value1", "field2": "value2", "answers": []}
        violations = contract.validate(result)
        assert len(violations) == 0

        # Missing field - should create violation
        result = {"field1": "value1", "answers": []}
        violations = contract.validate(result)
        assert len(violations) == 1
        assert "Missing required field: field2" in violations[0].message

    def test_validate_non_string_answers(self):
        """Contract should handle non-string answers gracefully."""
        contract = ExtractionContract()

        result = {"answers": [123, None, {"key": "value"}]}
        violations = contract.validate(result)

        # Should create violations for non-string types
        assert len(violations) == 3
        assert "Answer 0 is not a string" in violations[0].message
        assert "Answer 1 is not a string" in violations[1].message
        assert "Answer 2 is not a string" in violations[2].message


class TestExtractionResult:
    """Test ExtractionResult validation and behavior."""

    def test_valid_extraction_result(self):
        """Valid ExtractionResult should initialize correctly."""
        result = ExtractionResult(
            answers=["answer1", "answer2"],
            method="test_method",
            confidence=0.8,
            structured_data={"key": "value"},
        )

        assert result.answers == ["answer1", "answer2"]
        assert result.method == "test_method"
        assert result.confidence == 0.8
        assert result.structured_data == {"key": "value"}

    def test_extraction_result_defaults(self):
        """ExtractionResult should have appropriate defaults."""
        result = ExtractionResult(
            answers=["test"], method="test_method", confidence=0.5
        )

        assert result.structured_data is None

    def test_extraction_result_immutable(self):
        """ExtractionResult should be immutable."""
        result = ExtractionResult(
            answers=["test"], method="test_method", confidence=0.5
        )

        with pytest.raises(AttributeError):
            result.confidence = 0.8  # type: ignore

    def test_invalid_answers_type(self):
        """Non-list answers should raise ValueError."""
        with pytest.raises(ValueError, match="answers must be a list"):
            ExtractionResult(
                answers=cast("Any", "not a list"),
                method="test_method",
                confidence=0.5,
            )

    def test_empty_method(self):
        """Empty method should raise ValueError."""
        with pytest.raises(ValueError, match="method cannot be empty"):
            ExtractionResult(answers=["test"], method="", confidence=0.5)

    def test_invalid_confidence_range(self):
        """Confidence outside [0.0, 1.0] should raise ValueError."""
        with pytest.raises(ValueError, match="confidence must be in \\[0.0, 1.0\\]"):
            ExtractionResult(answers=["test"], method="test_method", confidence=-0.1)

        with pytest.raises(ValueError, match="confidence must be in \\[0.0, 1.0\\]"):
            ExtractionResult(answers=["test"], method="test_method", confidence=1.1)


class TestExtractionDiagnostics:
    """Test ExtractionDiagnostics mutable data collection."""

    def test_default_extraction_diagnostics(self):
        """Default ExtractionDiagnostics should have empty collections."""
        diagnostics = ExtractionDiagnostics()

        assert diagnostics.attempted_transforms == []
        assert diagnostics.successful_transform is None
        assert diagnostics.transform_errors == {}
        assert diagnostics.contract_violations == []
        assert diagnostics.flags == set()
        assert diagnostics.extraction_duration_ms is None

    def test_diagnostics_mutable(self):
        """ExtractionDiagnostics should be mutable for data collection."""
        diagnostics = ExtractionDiagnostics()

        # Should be able to modify fields
        diagnostics.attempted_transforms.append("transform1")
        diagnostics.successful_transform = "transform1"
        diagnostics.transform_errors["failed_transform"] = "error message"
        diagnostics.contract_violations.append(Violation("test violation"))
        diagnostics.flags.add("test_flag")
        diagnostics.extraction_duration_ms = 123.45

        assert diagnostics.attempted_transforms == ["transform1"]
        assert diagnostics.successful_transform == "transform1"
        assert diagnostics.transform_errors == {"failed_transform": "error message"}
        assert len(diagnostics.contract_violations) == 1
        assert diagnostics.flags == {"test_flag"}
        assert diagnostics.extraction_duration_ms == 123.45
