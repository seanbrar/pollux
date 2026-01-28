"""Unit tests for Result Builder core types and data structures.

Tests the fundamental data types that enable the Two-Tier Transform Chain,
focusing on validation, immutability, and contract adherence according
to the architecture rubric principles.
"""


import pytest

from pollux.pipeline.results.extraction import ExtractionContract

pytestmark = pytest.mark.unit


class TestExtractionContract:
    """Test ExtractionContract validation and behavior."""

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
