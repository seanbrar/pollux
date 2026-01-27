"""Unit tests for MinimalProjection fallback extractor.

Tests the infallible Tier 2 component of the Two-Tier Transform Chain,
verifying that it never fails and handles any input gracefully while
maintaining the architecture rubric's robustness principles.
"""

import pytest

from pollux.pipeline.results.extraction import ExtractionContext
from pollux.pipeline.results.minimal_projection import MinimalProjection

pytestmark = pytest.mark.unit


class TestMinimalProjection:
    """Test MinimalProjection infallible extraction behavior."""

    def setUp(self):
        """Set up test fixture."""
        self.projection = MinimalProjection()

    def test_simple_text_extraction(self):
        """MinimalProjection should handle simple text input."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=1)

        result = projection.extract("Simple text answer", ctx)

        assert result.answers == ["Simple text answer"]
        assert result.method == "minimal_text"
        assert result.confidence == 0.3
        assert len(result.answers) == 1

    def test_json_array_extraction(self):
        """MinimalProjection should parse valid JSON arrays."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=3)

        json_text = '["answer1", "answer2", "answer3"]'
        result = projection.extract(json_text, ctx)

        assert result.answers == ["answer1", "answer2", "answer3"]
        assert result.method == "minimal_json"
        assert result.confidence == 0.8
        assert len(result.answers) == 3

    def test_json_array_with_nulls(self):
        """MinimalProjection should handle JSON arrays with null values."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=3)

        json_text = '["answer1", null, "answer3"]'
        result = projection.extract(json_text, ctx)

        assert result.answers == ["answer1", "", "answer3"]
        assert result.method == "minimal_json"
        assert len(result.answers) == 3

    def test_numbered_list_extraction(self):
        """MinimalProjection should extract numbered lists."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=3)

        numbered_text = """
        1. First answer
        2. Second answer
        3. Third answer
        """
        result = projection.extract(numbered_text, ctx)

        assert result.answers == ["First answer", "Second answer", "Third answer"]
        assert result.method == "minimal_numbered"
        assert result.confidence == 0.6
        assert len(result.answers) == 3

    def test_newline_splitting(self):
        """MinimalProjection should split on newlines for multiple answers."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=3)

        multiline_text = """Answer one
        Answer two
        Answer three"""
        result = projection.extract(multiline_text, ctx)

        assert result.answers == ["Answer one", "Answer two", "Answer three"]
        assert result.method == "minimal_newlines"
        assert result.confidence == 0.5
        assert len(result.answers) == 3

    def test_padding_behavior(self):
        """MinimalProjection should pad answers to expected count."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=5)

        # Only 2 answers available, should pad to 5
        json_text = '["answer1", "answer2"]'
        result = projection.extract(json_text, ctx)

        assert len(result.answers) == 5
        assert result.answers == ["answer1", "answer2", "", "", ""]

    def test_truncation_behavior(self):
        """MinimalProjection should truncate excess answers."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=2)

        # 4 answers available, should truncate to 2
        json_text = '["answer1", "answer2", "answer3", "answer4"]'
        result = projection.extract(json_text, ctx)

        assert len(result.answers) == 2
        assert result.answers == ["answer1", "answer2"]

    def test_dict_input_simple_text(self):
        """MinimalProjection should extract text from dict inputs."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=1)

        dict_input = {"text": "Extracted text"}
        result = projection.extract(dict_input, ctx)

        assert result.answers == ["Extracted text"]
        assert result.method == "minimal_text"

    def test_dict_input_provider_structure(self):
        """MinimalProjection should navigate provider SDK structures."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=1)

        provider_response = {
            "candidates": [{"content": {"parts": [{"text": "Provider response text"}]}}]
        }
        result = projection.extract(provider_response, ctx)

        assert result.answers == ["Provider response text"]
        assert result.method == "minimal_text"

    def test_never_fails_with_invalid_input(self):
        """MinimalProjection should never fail, even with pathological input."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=1)

        # Test various pathological inputs
        test_inputs = [
            None,
            "",
            {},
            [],
            {"invalid": "structure"},
            Exception("test exception"),
            123,
            True,
            object(),
        ]

        for test_input in test_inputs:
            result = projection.extract(test_input, ctx)

            # Should always return a result
            assert isinstance(result.answers, list)
            assert len(result.answers) == 1
            assert isinstance(result.method, str)
            assert isinstance(result.confidence, float)
            assert 0.0 <= result.confidence <= 1.0

    def test_handles_malformed_json_gracefully(self):
        """MinimalProjection should handle malformed JSON without failing."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=1)

        malformed_json = '{"incomplete": json'
        result = projection.extract(malformed_json, ctx)

        # Should fall back to text extraction
        assert result.answers == [malformed_json]
        assert result.method == "minimal_text"

    def test_handles_empty_or_whitespace_input(self):
        """MinimalProjection should handle empty/whitespace input gracefully."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=2)

        # Empty string
        result = projection.extract("", ctx)
        assert len(result.answers) == 2
        assert result.answers == ["", ""]

        # Whitespace only
        result = projection.extract("   \n\t  ", ctx)
        assert len(result.answers) == 2
        # Whitespace gets stripped, so becomes empty
        assert result.answers[0] == ""

    def test_nested_list_flattening(self):
        """MinimalProjection should flatten nested lists appropriately."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=3)

        # Nested JSON array
        json_text = '[["answer1", "answer2"], "answer3"]'
        result = projection.extract(json_text, ctx)

        # Should flatten the nested structure
        assert len(result.answers) == 3
        assert "answer1" in result.answers
        assert "answer3" in result.answers

    def test_various_numbered_list_formats(self):
        """MinimalProjection should handle different numbered list formats."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=3)

        # Test different formats
        formats = [
            "1. Answer one\n2. Answer two\n3. Answer three",  # Standard
            "1) Answer one\n2) Answer two\n3) Answer three",  # Parentheses
            "[1] Answer one\n[2] Answer two\n[3] Answer three",  # Brackets
        ]

        for format_text in formats:
            result = projection.extract(format_text, ctx)

            assert len(result.answers) == 3
            assert result.method == "minimal_numbered"
            assert "Answer one" in result.answers
            assert "Answer three" in result.answers

    def test_confidence_levels_are_ordered(self):
        """MinimalProjection confidence should reflect extraction quality."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=2)

        # JSON should have highest confidence
        json_result = projection.extract('["a", "b"]', ctx)

        # Numbered list should have medium confidence
        numbered_result = projection.extract("1. a\n2. b", ctx)

        # Newlines should have lower confidence
        newline_result = projection.extract("a\nb", ctx)

        # Text fallback should have lowest confidence
        text_result = projection.extract("single answer", ctx)

        assert json_result.confidence > numbered_result.confidence
        assert numbered_result.confidence > newline_result.confidence
        assert newline_result.confidence > text_result.confidence

    def test_robust_text_extraction_from_objects(self):
        """MinimalProjection should extract text from various object types."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=1)

        # Object with text attribute
        class MockObject:
            def __init__(self, text: str) -> None:
                self.text = text

        obj = MockObject("Object text content")
        result = projection.extract(obj, ctx)

        assert result.answers == ["Object text content"]

    def test_handles_string_conversion_failures(self):
        """MinimalProjection should handle str() conversion failures gracefully."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=1)

        # Object that raises exception on str()
        class BadStringObject:
            def __str__(self):
                raise RuntimeError("Cannot convert to string")

        bad_obj = BadStringObject()
        result = projection.extract(bad_obj, ctx)

        # Should still return a result
        assert isinstance(result.answers, list)
        assert len(result.answers) == 1
        assert result.answers[0] == "[unparseable content]"

    def test_deterministic_behavior(self):
        """MinimalProjection should produce identical results for same input."""
        projection = MinimalProjection()
        ctx = ExtractionContext(expected_count=2)

        test_input = '["consistent", "answer"]'

        # Extract multiple times
        result1 = projection.extract(test_input, ctx)
        result2 = projection.extract(test_input, ctx)
        result3 = projection.extract(test_input, ctx)

        # Results should be identical
        assert result1.answers == result2.answers == result3.answers
        assert result1.method == result2.method == result3.method
        assert result1.confidence == result2.confidence == result3.confidence
